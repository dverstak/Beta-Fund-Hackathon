"""Core data models for the audit pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class LineItem:
    """A single auditable transaction (income or expense)."""
    source: str                  # source file
    profile: str                 # receipt | form_1099nec | spreadsheet
    date: Optional[str] = None   # ISO yyyy-mm-dd
    vendor: Optional[str] = None
    description: Optional[str] = None
    amount: float = 0.0
    kind: str = "expense"        # "income" | "expense"
    payment_method: Optional[str] = None
    raw: dict = field(default_factory=dict)

    # filled by categorizer
    schedule_c_line: Optional[str] = None     # e.g. "Line 24a Travel"
    category: Optional[str] = None
    deductible_pct: float = 100.0
    confidence: float = 0.0
    rationale: Optional[str] = None

    # filled by risk flagger
    risk_level: str = "low"      # low | medium | high
    flags: list[str] = field(default_factory=list)

    @property
    def deductible_amount(self) -> float:
        if self.kind != "expense":
            return 0.0
        return round(self.amount * self.deductible_pct / 100.0, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deductible_amount"] = self.deductible_amount
        return d
