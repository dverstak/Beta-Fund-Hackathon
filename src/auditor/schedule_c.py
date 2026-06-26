"""IRS Schedule C (Form 1040) expense lines + categorization knowledge.

Part II expense lines used to classify deductions. `pct` is the default
deductible percentage (meals are 50%). Reference only -- not tax advice.
"""
from __future__ import annotations

# line code -> (label, default deductible %)
SCHEDULE_C_LINES: dict[str, tuple[str, float]] = {
    "8":   ("Advertising", 100.0),
    "9":   ("Car and truck expenses", 100.0),
    "10":  ("Commissions and fees", 100.0),
    "11":  ("Contract labor", 100.0),
    "12":  ("Depletion", 100.0),
    "13":  ("Depreciation / Section 179", 100.0),
    "14":  ("Employee benefit programs", 100.0),
    "15":  ("Insurance (other than health)", 100.0),
    "16a": ("Interest - mortgage", 100.0),
    "16b": ("Interest - other", 100.0),
    "17":  ("Legal and professional services", 100.0),
    "18":  ("Office expense", 100.0),
    "19":  ("Pension and profit-sharing plans", 100.0),
    "20a": ("Rent/lease - vehicles, machinery, equipment", 100.0),
    "20b": ("Rent/lease - other business property", 100.0),
    "21":  ("Repairs and maintenance", 100.0),
    "22":  ("Supplies", 100.0),
    "23":  ("Taxes and licenses", 100.0),
    "24a": ("Travel", 100.0),
    "24b": ("Deductible meals (50%)", 50.0),
    "25":  ("Utilities", 100.0),
    "26":  ("Wages", 100.0),
    "27a": ("Other expenses", 100.0),
    "30":  ("Home office (Form 8829)", 100.0),
    "NONDEDUCTIBLE": ("Non-deductible / personal", 0.0),
}

INCOME_LINE = ("1", "Gross receipts (incl. 1099-NEC)")

# Compact reference handed to the model so it maps to valid line codes.
LINE_REFERENCE = "\n".join(
    f"  {code}: {label} (default {pct:.0f}% deductible)"
    for code, (label, pct) in SCHEDULE_C_LINES.items()
)


def line_label(code: str) -> str:
    return SCHEDULE_C_LINES.get(code, ("Unknown line", 100.0))[0]


def default_pct(code: str) -> float:
    return SCHEDULE_C_LINES.get(code, ("", 100.0))[1]
