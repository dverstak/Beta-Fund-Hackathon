"""Generate demo data: a transactions CSV, two receipt images, one 1099-NEC.

Receipts/1099 are rendered as slightly messy images so the GMI vision model
has something realistic (and chaotic) to parse. Run:
    python scripts/make_samples.py
"""
from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DATA = Path(__file__).resolve().parents[1] / "data"


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_csv():
    rows = [
        ["date", "vendor", "description", "amount", "type", "payment"],
        ["2025-01-15", "Adobe", "Creative Cloud subscription", "59.99", "expense", "card"],
        ["2025-02-03", "United Airlines", "Flight to client onsite SFO", "412.40", "expense", "card"],
        ["2025-02-03", "Hyatt", "Hotel 2 nights client trip", "388.00", "expense", "card"],
        ["2025-02-20", "Steakhouse 55", "Client dinner", "240.00", "expense", "card"],
        ["2025-03-01", "WeWork", "Coworking desk monthly", "350.00", "expense", "card"],
        ["2025-03-12", "Best Buy", "Laptop for business", "2399.00", "expense", "card"],
        ["2025-03-30", "Nordstrom", "New suit", "650.00", "expense", "card"],
        ["2025-04-05", "Acme Corp", "Project milestone payment", "8500.00", "income", "ach"],
        ["2025-04-18", "Shell", "Gas - client site visits", "300.00", "expense", "cash"],
        ["2025-05-02", "LegalZoom", "LLC filing + legal", "299.00", "expense", "card"],
        ["2025-05-15", "Staples", "Office supplies", "84.25", "expense", "card"],
        ["2025-06-01", "State Farm", "Business liability insurance", "540.00", "expense", "card"],
        ["2024-12-28", "Verizon", "Phone bill (prior year)", "95.00", "expense", "card"],
    ]
    out = DATA / "transactions.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    print("wrote", out)


def _receipt(path: Path, lines: list[tuple[str, int]], w=520, h=720):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    y = 30
    for text, size in lines:
        d.text((40, y), text, fill=(20, 20, 20), font=_font(size))
        y += size + 14
    # a little noise/skew to mimic a phone photo
    img = img.rotate(-2.5, expand=True, fillcolor="white")
    img.save(path)
    print("wrote", path)


def make_receipts():
    _receipt(DATA / "receipt_office_depot.png", [
        ("OFFICE DEPOT #2241", 30),
        ("1450 Market St", 20),
        ("------------------------", 20),
        ("Printer Ink HP 952XL    $89.99", 22),
        ("Copy Paper 5-ream       $42.50", 22),
        ("USB-C Hub               $34.99", 22),
        ("------------------------", 20),
        ("SUBTOTAL              $167.48", 22),
        ("TAX                    $14.21", 22),
        ("TOTAL                 $181.69", 26),
        ("VISA ****4412", 20),
        ("03/22/2025  10:42 AM", 20),
    ])
    _receipt(DATA / "receipt_cafe.png", [
        ("THE CORNER CAFE", 30),
        ("Downtown", 20),
        ("------------------------", 20),
        ("Latte x2               $11.00", 22),
        ("Avocado Toast           $14.50", 22),
        ("Business mtg w/ client", 18),
        ("------------------------", 20),
        ("TOTAL                  $25.50", 26),
        ("CASH", 20),
        ("04/11/2025", 20),
    ])


def make_1099():
    img = Image.new("RGB", (640, 480), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 630, 470], outline=(0, 0, 0), width=2)
    rows = [
        ("Form 1099-NEC  (2025)", 26),
        ("Nonemployee Compensation", 20),
        ("PAYER: Globex Consulting LLC", 20),
        ("PAYER TIN: 81-2345678", 18),
        ("RECIPIENT: Jordan Freelancer", 20),
        ("RECIPIENT TIN: ***-**-1234", 18),
        ("Box 1  Nonemployee comp:  $42,750.00", 22),
        ("Box 4  Federal tax withheld:  $0.00", 20),
    ]
    y = 30
    for text, size in rows:
        d.text((30, y), text, fill=(10, 10, 10), font=_font(size))
        y += size + 16
    path = DATA / "1099-nec_globex.png"
    img.save(path)
    print("wrote", path)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    make_csv()
    make_receipts()
    make_1099()
    print("Sample data ready in", DATA)
