"""Invoice vertical tests — deterministic, no network (stub brain, generated PDFs)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from eeze_agent.verticals.invoices import run_vertical
from eeze_agent.verticals.invoices.llm import BrainResult
from eeze_agent.verticals.invoices.schema import FieldValue, InvoiceExtraction
from eeze_agent.verticals.invoices.verify import (
    normalize_text,
    parse_amount,
    parse_date,
    verify_field,
)

TODAY = date(2026, 9, 18)


def _v(field: str, value: str | None, quote: str | None, source: str):
    return verify_field(field, value, quote, normalize_text(source))


# --- literalism checks -------------------------------------------------------


def test_amount_eu_separators_verified():
    source = "Gesamtbetrag: EUR 3.499,00\nFällig am: 21.10.2026"
    verdict = _v("total_amount", "3.499,00", "Gesamtbetrag: EUR 3.499,00", source)
    assert verdict.status == "verified"


def test_amount_us_separators_verified():
    source = "Total amount due: $5,760.40"
    verdict = _v("total_amount", "5,760.40", "Total amount due: $5,760.40", source)
    assert verdict.status == "verified"


def test_amount_wrong_value_flagged():
    verdict = _v("total_amount", "4.999,00", "Gesamtbetrag: EUR 3.499,00", "Gesamtbetrag: EUR 3.499,00")
    assert verdict.status == "unverified"
    assert verdict.reason == "value_not_in_quote"


def test_date_spelled_out_verified():
    source = "Issued: August 3, 2026\nPayment due: October 2, 2026"
    verdict = _v("due_date", "2026-10-02", "Payment due: October 2, 2026", source)
    assert verdict.status == "verified"


def test_date_iso_verified():
    verdict = _v("due_date", "2026-10-14", "Due Date: 2026-10-14", "Due Date: 2026-10-14")
    assert verdict.status == "verified"


def test_quote_not_in_source_flagged():
    verdict = _v("vendor", "Ghost LLC", "Ghost LLC", "Acme Ltda\nTotal: EUR 5,00")
    assert verdict.status == "unverified"
    assert verdict.reason == "quote_not_in_source"


def test_missing_field_is_missing_not_zero():
    verdict = _v("due_date", None, None, "Total: EUR 5,00")
    assert verdict.status == "missing"
    assert verdict.value is None


def test_no_quote_is_unverified():
    verdict = _v("vendor", "Acme Ltda", None, "Acme Ltda")
    assert verdict.status == "unverified"
    assert verdict.reason == "no_quote"


def test_currency_symbol_matches_iso():
    source = "Valor total: R$ 12.500,00"
    verdict = _v("currency", "BRL", "Valor total: R$ 12.500,00", source)
    assert verdict.status == "verified"


# --- parsers -----------------------------------------------------------------


def test_parse_amount_variants():
    assert parse_amount("1.234,50") == 1234.5
    assert parse_amount("1,234.50") == 1234.5
    assert parse_amount("999,00") == 999.0
    assert parse_amount("R$ 12.500,00") == 12500.0
    assert parse_amount("no digits here") is None


def test_parse_date_variants():
    assert parse_date("22.03.2026") == date(2026, 3, 22)
    assert parse_date("March 3, 2026") == date(2026, 3, 3)
    assert parse_date("2026-03-15") == date(2026, 3, 15)
    assert parse_date("14/09/2026") == date(2026, 9, 14)
    assert parse_date("gibberish") is None


# --- pipeline (stub brain) ---------------------------------------------------


class StubBrain:
    def __init__(self, fields: dict[str, FieldValue]):
        self.fields = fields
        self.calls: list[str] = []

    def extract(self, text: str) -> BrainResult:
        self.calls.append(text)
        return BrainResult(
            extraction=InvoiceExtraction(fields=self.fields),
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            model="stub",
        )


def _write_pdf(path: Path, lines: list[str]) -> None:
    """Write a minimal single-page text PDF — no third-party PDF library.

    PyMuPDF (AGPL) was dropped from the project (see F6 checklist item 10) and pypdf cannot
    AUTHOR text pages, so the fixture writes a valid 1-page PDF by hand: base-14 Helvetica,
    one line per entry, WinAnsi so accents survive. `lines=[]` produces a page with no text
    (the image-only case).
    """
    body = ["BT /F1 11 Tf 72 720 Td 16 TL"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        body.append(f"({escaped}) Tj T*")
    body.append("ET")
    content = "\n".join(body).encode("cp1252", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))


def _stub_fields(due_value: str, due_quote: str) -> dict[str, FieldValue]:
    return {
        "vendor": FieldValue(value="Acme Ltda", quote="Acme Ltda"),
        "invoice_number": FieldValue(value="INV-1", quote="Invoice No: INV-1"),
        "total_amount": FieldValue(value="100,00", quote="Total: EUR 100,00"),
        "currency": FieldValue(value="EUR", quote="Total: EUR 100,00"),
        "issue_date": FieldValue(),
        "due_date": FieldValue(value=due_value, quote=due_quote),
    }


def test_pipeline_flags_duplicates(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    lines = ["Acme Ltda", "Invoice No: INV-1", "Total: EUR 100,00", "Due date: 10/10/2026"]
    _write_pdf(corpus / "a.pdf", lines)
    _write_pdf(corpus / "b.pdf", lines)
    stub = StubBrain(_stub_fields("2026-10-10", "Due date: 10/10/2026"))

    summary = run_vertical(corpus, tmp_path / "out", brain=stub, today=TODAY)

    assert summary["files"] == 2
    assert summary["flagged"] == 2
    assert summary["tokens"] == {"input": 20, "output": 10}
    ledger = (tmp_path / "out" / "ledger.csv").read_text(encoding="utf-8")
    assert "due_date_iso" in ledger
    assert "2026-10-10" in ledger  # derived ISO column present
    assert ledger.count("DUPLICATE:") >= 2
    report = (tmp_path / "out" / "anomalies.md").read_text(encoding="utf-8")
    assert "DUPLICATE_INVOICE" in report
    assert "MISSING_FIELD" in report  # issue_date intentionally absent


def test_pipeline_no_text_layer_skips_brain(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write_pdf(corpus / "blank.pdf", [])  # one page, no text layer
    stub = StubBrain(_stub_fields("2026-10-10", "never used"))

    summary = run_vertical(corpus, tmp_path / "out", brain=stub, today=TODAY)

    assert stub.calls == []
    assert summary["flagged"] == 1
    assert summary["tokens"] is None  # no brain usage seen: null, not 0
    report = (tmp_path / "out" / "anomalies.md").read_text(encoding="utf-8")
    assert "NO_TEXT_LAYER" in report


def test_pipeline_overdue_flag(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write_pdf(
        corpus / "late.pdf",
        ["Acme Ltda", "Invoice No: INV-9", "Total: EUR 100,00", "Due date: 14/09/2026"],
    )
    stub = StubBrain(_stub_fields("2026-09-14", "Due date: 14/09/2026"))

    summary = run_vertical(corpus, tmp_path / "out", brain=stub, today=TODAY)

    assert summary["flagged"] == 1
    report = (tmp_path / "out" / "anomalies.md").read_text(encoding="utf-8")
    assert "OVERDUE" in report


def test_pipeline_survives_brain_error(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _write_pdf(corpus / "x.pdf", ["Acme Ltda", "Total: EUR 1,00"])

    class BoomBrain:
        def extract(self, text: str):
            raise RuntimeError("brain exploded")

    summary = run_vertical(corpus, tmp_path / "out", brain=BoomBrain(), today=TODAY)

    assert summary["files"] == 1
    assert summary["flagged"] == 1
    report = (tmp_path / "out" / "anomalies.md").read_text(encoding="utf-8")
    assert "EXTRACT_ERROR" in report
