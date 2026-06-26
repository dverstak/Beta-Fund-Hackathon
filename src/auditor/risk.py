"""Deterministic high-risk deduction flagging (audit-trigger heuristics).

Rules-based so flags are explainable and reproducible -- no tokens spent.
Mirrors common IRS audit triggers for Schedule C filers.
"""
from __future__ import annotations

from .models import LineItem
from . import config

# expense lines that draw extra IRS scrutiny for contractors
_SCRUTINY_LINES = {"9": "Vehicle expense", "24a": "Travel",
                   "24b": "Meals", "30": "Home office", "13": "Depreciation/179"}
_HIGH_AMOUNT = 5000.0
_MISSING_DOC_AMOUNT = 75.0   # IRS substantiation threshold for travel/meals


def flag(items: list[LineItem]) -> None:
    seen: dict[tuple, int] = {}
    for it in items:
        flags: list[str] = []
        code = it.raw.get("_line_code", "")

        if it.kind == "expense":
            if it.confidence and it.confidence < 0.5:
                flags.append(f"Low categorization confidence ({it.confidence:.2f})")
            if code in _SCRUTINY_LINES:
                flags.append(f"Audit-sensitive category: {_SCRUTINY_LINES[code]}")
            if it.amount >= _HIGH_AMOUNT:
                flags.append(f"Large deduction (${it.amount:,.2f})")
            if it.amount == round(it.amount) and it.amount >= 500 and \
                    str(int(it.amount)).endswith("00"):
                flags.append("Suspiciously round amount")
            if code == "NONDEDUCTIBLE" or it.deductible_pct == 0:
                flags.append("Personal / non-deductible expense claimed")
            if code == "24b" and it.deductible_pct > 50:
                flags.append("Meals over 50% deductible limit")
            if it.profile == "spreadsheet" and it.amount >= _MISSING_DOC_AMOUNT \
                    and code in ("24a", "24b", "9"):
                flags.append("No supporting receipt for substantiation-required expense")
            if (it.payment_method or "").lower() == "cash" and it.amount >= 200:
                flags.append("Cash payment >$200 (weak audit trail)")

        if not it.date:
            flags.append("Missing transaction date")
        elif it.date[:4].isdigit() and int(it.date[:4]) != config.TAX_YEAR:
            flags.append(f"Date outside tax year {config.TAX_YEAR}")

        # duplicate detection
        key = (round(it.amount, 2), (it.vendor or "").lower(), it.date)
        if it.amount and key in seen:
            flags.append("Possible duplicate transaction")
        else:
            seen[key] = 1

        it.flags = flags
        it.risk_level = _level(flags)


def _level(flags: list[str]) -> str:
    if not flags:
        return "low"
    high = ("non-deductible", "duplicate", "over 50%", "outside tax year",
            "Large deduction", "No supporting receipt")
    if any(any(h.lower() in f.lower() for h in high) for f in flags):
        return "high"
    return "medium"
