"""Clerk authentication helpers for the FastAPI app.

We use Clerk's *hosted* sign-in/sign-up pages, so there is no auth UI in this
repo. The flow is:

    1. A signed-out browser hits a protected page -> we redirect to Clerk's
       hosted sign-in URL (with ?redirect_url back to where they were).
    2. Clerk handles sign-in/sign-up and sets its session cookie, then sends
       the user back to us.
    3. On every protected request we hand the incoming request to Clerk's
       backend SDK, which verifies the session (cookie or Bearer token).

Required environment variables (set locally in .env and in Vercel):

    CLERK_SECRET_KEY              sk_test_... / sk_live_...   (server secret)
    CLERK_PUBLISHABLE_KEY        pk_test_... / pk_live_...   (used to derive
                                  the default hosted sign-in URL)

Optional:
    CLERK_SIGN_IN_URL            override the hosted sign-in URL explicitly
    CLERK_AUTHORIZED_PARTIES     comma-separated allowed origins for CSRF
                                  protection, e.g. "https://yourapp.vercel.app"
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Optional

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import HTTPException, Request

try:  # Local dev: load .env. On Vercel, env vars are injected directly.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed (fine in production)
    pass


@lru_cache(maxsize=1)
def _clerk() -> Clerk:
    secret = os.environ.get("CLERK_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "CLERK_SECRET_KEY is not set. Add it to your environment "
            "(.env locally, `vercel env add` in production)."
        )
    return Clerk(bearer_auth=secret)


def _authorized_parties() -> Optional[list[str]]:
    raw = os.environ.get("CLERK_AUTHORIZED_PARTIES", "").strip()
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def _publishable_key() -> str:
    return (
        os.environ.get("CLERK_PUBLISHABLE_KEY")
        or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
        or ""
    )


@lru_cache(maxsize=1)
def _frontend_api_origin() -> str:
    """Derive the Clerk Frontend API origin from the publishable key.

    A publishable key looks like `pk_test_<base64-of-frontend-host>`. The
    base64 segment decodes to e.g. `polished-sponge-93.clerk.accounts.dev$`.
    Note this is the *API* host, not the hosted sign-in (Account Portal) host.
    """
    pk = _publishable_key()
    try:
        b64 = pk.split("_", 2)[2]
        host = base64.b64decode(b64 + "==").decode().rstrip("$")
        return f"https://{host}"
    except Exception:  # noqa: BLE001 - any malformed key falls back below
        return ""


@lru_cache(maxsize=1)
def _account_portal() -> dict[str, str]:
    """Fetch the hosted sign-in/sign-up URLs from Clerk's environment endpoint.

    This is authoritative for both dev (`*.accounts.dev`) and production
    (custom `accounts.<domain>`) instances, so we don't have to guess the
    Account Portal host. Falls back to the dev-domain heuristic if the call
    fails (e.g. offline).
    """
    fapi = _frontend_api_origin()
    try:
        resp = httpx.get(
            f"{fapi}/v1/environment",
            params={"__clerk_api_version": "2024-10-01", "_clerk_js_version": "5"},
            timeout=5.0,
        )
        dc = resp.json().get("display_config", {})
        si, su = dc.get("sign_in_url"), dc.get("sign_up_url")
        if si and su:
            return {"sign_in": si, "sign_up": su}
    except Exception:  # noqa: BLE001 - fall back to heuristic below
        pass
    # Heuristic fallback: dev Account Portal drops the ".clerk" subdomain.
    portal = fapi.replace(".clerk.accounts.dev", ".accounts.dev")
    return {"sign_in": f"{portal}/sign-in", "sign_up": f"{portal}/sign-up"}


def sign_in_url(return_to: str = "/") -> str:
    """The hosted Clerk sign-in URL to redirect signed-out users to."""
    base = os.environ.get("CLERK_SIGN_IN_URL", "").strip() or _account_portal()["sign_in"]
    # Clerk's Account Portal accepts redirect_url to return after sign-in.
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}redirect_url={return_to}"


def _to_httpx_request(request: Request) -> httpx.Request:
    """Adapt a Starlette request into the httpx.Request Clerk expects."""
    return httpx.Request(
        method=request.method,
        url=str(request.url),
        headers=dict(request.headers),
    )


def get_user_id(request: Request) -> Optional[str]:
    """Return the Clerk user id if the request is signed in, else None."""
    state = _clerk().authenticate_request(
        _to_httpx_request(request),
        AuthenticateRequestOptions(authorized_parties=_authorized_parties()),
    )
    if not state.is_signed_in:
        return None
    payload = state.payload or {}
    return payload.get("sub")


def require_user(request: Request) -> str:
    """FastAPI dependency for protected API routes: return the user id or 401.

    We return a JSON 401 (not a redirect) because these endpoints are called by
    `fetch()` from the SPA. The browser-side Clerk gate handles redirecting a
    signed-out *visitor* to the hosted sign-in page; the API just rejects
    unauthenticated requests.
    """
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


def public_config() -> dict[str, str]:
    """Non-secret config the browser needs to boot Clerk JS."""
    return {
        "publishableKey": _publishable_key(),
        "signInUrl": sign_in_url(),
    }
