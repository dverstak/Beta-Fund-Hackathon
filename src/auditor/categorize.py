"""Categorize expenses to Schedule C lines via GMI reasoning model + rules."""
from __future__ import annotations

import json

from .gmi_client import GMIClient
from .models import LineItem
from . import schedule_c

SYSTEM = (
    "You are a US tax bookkeeping engine specializing in Schedule C (Form 1040) "
    "for self-employed independent contractors. Map each business expense to the "
    "single most appropriate Schedule C line code. Be conservative and accurate. "
    "Personal/clearly non-deductible items map to 'NONDEDUCTIBLE'. Meals are "
    "line 24b at 50%. Return STRICT JSON only."
)


def _prompt(batch: list[LineItem]) -> str:
    rows = [{"id": i, "vendor": it.vendor, "description": it.description,
             "amount": it.amount} for i, it in enumerate(batch)]
    return (
        "Schedule C expense lines:\n" + schedule_c.LINE_REFERENCE +
        "\n\nClassify each expense. For every id return: line_code (one of the "
        "codes above), deductible_pct (number), confidence (0-1), rationale "
        "(short).\n\nExpenses:\n" + json.dumps(rows, indent=2) +
        '\n\nReturn JSON: {"items": [{"id": int, "line_code": str, '
        '"deductible_pct": number, "confidence": number, "rationale": str}]}'
    )


def categorize(client: GMIClient, items: list[LineItem],
               batch_size: int = 25) -> None:
    """Annotate expense items in place. Income items are skipped."""
    expenses = [it for it in items if it.kind == "expense"]
    for start in range(0, len(expenses), batch_size):
        batch = expenses[start:start + batch_size]
        result = client.reason_json("reasoning", SYSTEM, _prompt(batch),
                                    max_tokens=3000)
        by_id = {r.get("id"): r for r in result.get("items", [])}
        for i, it in enumerate(batch):
            r = by_id.get(i, {})
            code = r.get("line_code") or "27a"
            if code not in schedule_c.SCHEDULE_C_LINES:
                code = "27a"
            it.schedule_c_line = f"Line {code} - {schedule_c.line_label(code)}"
            it.category = schedule_c.line_label(code)
            it.deductible_pct = float(r.get("deductible_pct",
                                            schedule_c.default_pct(code)))
            it.confidence = float(r.get("confidence", 0.0))
            it.rationale = r.get("rationale")
            it.raw["_line_code"] = code
