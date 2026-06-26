"""Ingest: walk an input path and classify each file into a document profile."""
from __future__ import annotations

from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
SHEET_EXT = {".csv", ".tsv", ".xlsx", ".xls"}
PDF_EXT = {".pdf"}

# filename hints used to guess profile for image/pdf docs
_1099_HINTS = ("1099", "nec", "misc")


def classify(path: Path) -> str:
    """Return one of: spreadsheet | form_1099nec | receipt | pdf | unknown."""
    ext = path.suffix.lower()
    name = path.name.lower()
    if ext in SHEET_EXT:
        return "spreadsheet"
    if ext in IMAGE_EXT or ext in PDF_EXT:
        if any(h in name for h in _1099_HINTS):
            return "form_1099nec"
        return "receipt"
    return "unknown"


def discover(input_path: Path) -> list[tuple[Path, str]]:
    """Return [(file, profile)] for every supported file under input_path."""
    files: list[Path] = []
    if input_path.is_dir():
        files = sorted(p for p in input_path.rglob("*") if p.is_file())
    elif input_path.is_file():
        files = [input_path]
    out = []
    for f in files:
        profile = classify(f)
        if profile != "unknown":
            out.append((f, profile))
    return out
