"""Generate the synthetic invoice corpus for the E1 vertical (clearly marked test data).

Planted cases: duplicate pair, missing due date, no text layer, EU/US/BRL/GBP
number+date formats, one overdue invoice.

Run:  uv run python scripts/make_synthetic_invoices.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

INVOICES: list[tuple[str, list[str]]] = [
    (
        "2026-0101_acme.pdf",
        [
            "ACME Industrial Supply GmbH",
            "Invoice No: INV-2026-0101",
            "Invoice date: 12/08/2026",
            "Due date: 11/10/2026",
            "Subtotal: EUR 4.100,00",
            "VAT (19%): EUR 779,00",
            "TOTAL DUE: EUR 4.879,00",
        ],
    ),
    (
        "2026-0102_glacier.pdf",
        [
            "Glacier Analytics Inc.",
            "Invoice #INV-2026-0102",
            "Issued: August 3, 2026",
            "Payment due: October 2, 2026",
            "Amount due: $2,450.00",
        ],
    ),
    (
        "2026-0103_fitzworks.pdf",
        [
            "Fitzworks Automation Ltd",
            "Invoice Number: INV-2026-0103",
            "Issue Date: 2026-08-15",
            "Due Date: 2026-10-14",
            "Total: GBP 1,890.50",
        ],
    ),
    (
        "2026-0104_nucleo.pdf",
        [
            "Núcleo Design Ltda",
            "Invoice No: INV-2026-0104",
            "Data de emissão: 18/08/2026",
            "Due date: 17/10/2026",
            "Valor total: R$ 12.500,00",
        ],
    ),
    (
        "2026-0104_nucleo_duplicate.pdf",
        [
            "Núcleo Design Ltda",
            "Invoice No: INV-2026-0104",
            "Data de emissão: 19/08/2026",
            "Due date: 18/10/2026",
            "Valor total: R$ 12.500,00",
        ],
    ),
    (
        "2026-0106_boreal.pdf",
        [
            "Boreal Logistics SL",
            "Invoice No: INV-2026-0106",
            "Issue date: 20/08/2026",
            "Total: EUR 780,00",
            "Payment terms: 30 days",
        ],
    ),
    (
        "2026-0108_mueller.pdf",
        [
            "Müller & Söhne GmbH",
            "Invoice No: INV-2026-0108",
            "Rechnungsdatum: 22.08.2026",
            "Fällig am: 21.10.2026",
            "Gesamtbetrag: EUR 3.499,00",
        ],
    ),
    (
        "2026-0109_pacific.pdf",
        [
            "Pacific Crest Freight Co.",
            "Invoice No: INV-2026-0109",
            "Date of issue: August 25, 2026",
            "Payment due: October 24, 2026",
            "Total amount due: $5,760.40",
        ],
    ),
    (
        "2026-0110_vantage.pdf",
        [
            "Vantage Support Partners",
            "Invoice No: INV-2026-0110",
            "Issue date: 15/07/2026",
            "Due date: 14/09/2026",
            "Total: EUR 2.100,00",
        ],
    ),
]


def write_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 50), "SYNTHETIC TEST DOCUMENT - no real data", fontsize=8)
    y = 90
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    doc.save(path)
    doc.close()


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/e1-invoices/corpus")
    out.mkdir(parents=True, exist_ok=True)
    for name, lines in INVOICES:
        write_pdf(out / name, lines)
    blank = fitz.open()
    blank.new_page()
    blank.save(out / "2026-0107_notext.pdf")
    blank.close()
    print(f"wrote {len(INVOICES) + 1} synthetic invoices to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
