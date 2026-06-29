/* Clerk authentication gate.
 *
 * Loaded before app.js. Responsibilities:
 *   1. Boot Clerk JS (which consumes the dev-browser token on localhost and
 *      establishes the session — this is what fixes the redirect loop).
 *   2. If the visitor is signed out, redirect to Clerk's hosted sign-in page.
 *   3. If signed in, attach the session token as a Bearer header on every
 *      same-origin /api/* request, then load the real app (app.js).
 *
 * The publishable key + Frontend API host come from /api/clerk-config so we
 * never hardcode them and they work unchanged in production.
 */
(async () => {
  const reveal = () => document.documentElement.removeAttribute("data-clerk-loading");

  let cfg;
  try {
    cfg = await fetch("/api/clerk-config").then((r) => r.json());
  } catch {
    // Auth not configured (e.g. static hosting) — just show the app.
    reveal();
    loadApp();
    return;
  }

  const pubKey = cfg.publishableKey;
  if (!pubKey) {
    reveal();
    loadApp();
    return;
  }

  // Clerk JS is served from the Frontend API host, which is encoded in the
  // publishable key: pk_test_<base64(frontend-host)>.
  const fapiHost = atob(pubKey.split("_")[2]).replace(/\$$/, "");
  await loadScript(
    `https://${fapiHost}/npm/@clerk/clerk-js@5/dist/clerk.browser.js`,
    { "data-clerk-publishable-key": pubKey }
  );

  await window.Clerk.load();

  if (!window.Clerk.user) {
    // Signed out: hand off to the hosted sign-in page, returning here after.
    window.Clerk.redirectToSignIn({
      signInFallbackRedirectUrl: window.location.href,
      redirectUrl: window.location.href,
    });
    return; // page is navigating away
  }

  // Signed in: transparently authenticate same-origin API calls.
  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (url && (url.startsWith("/api") || url.startsWith(location.origin + "/api"))) {
      try {
        const token = await window.Clerk.session.getToken();
        init = {
          ...init,
          headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` },
        };
      } catch { /* fall through unauthenticated */ }
    }
    return origFetch(input, init);
  };

  reveal();
  loadApp();

  function loadApp() {
    const s = document.createElement("script");
    s.src = "/static/app.js";
    document.body.appendChild(s);
  }

  function loadScript(src, attrs = {}) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.async = true;
      s.crossOrigin = "anonymous";
      for (const [k, v] of Object.entries(attrs)) s.setAttribute(k, v);
      s.src = src;
      s.addEventListener("load", resolve);
      s.addEventListener("error", reject);
      document.head.appendChild(s);
    });
  }
})();
