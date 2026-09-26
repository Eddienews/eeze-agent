"""Invoice vertical pipeline: a folder of PDFs -> ledger.csv + anomalies.md.

Read-only by design: nothing leaves the machine except the extraction call to the
configured (local-first) brain. Failed files never kill the batch; every metric
that is unknown stays null — never a fabricated zero.

Text extraction uses **pypdf** (BSD-3-Clause). PyMuPDF was dropped on 2026-09-23: its
AGPL-3.0 (or commercial) license conflicts with the permissive Apache-2.0 OSS engine
distribution (F6 checklist item 10). Swapping back is a one-function change if a scanned
invoice ever needs OCR — that belongs to a separate, explicitly licensed module.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from .anomalies import analyze
from .ledger import write_anomalies_report, write_ledger
from .llm import ExtractionBrain
from .schema import CORE_FIELDS
from .verify import normalize_text, verify_field


def extract_pdf_text(path: Path) -> str:
    """All text of the PDF, page order preserved (empty string when image-only)."""
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def run_vertical(
    input_dir: Path,
    out_dir: Path,
    brain: ExtractionBrain | None = None,
    limit: int | None = None,
    model: str | None = None,
    today: date | None = None,
) -> dict:
    """Run the invoice vertical over ``input_dir`` and write the outputs to ``out_dir``."""
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(p for p in input_dir.glob("*.pdf") if p.is_file())
    if limit is not None:
        pdfs = pdfs[:limit]

    brain = brain or ExtractionBrain(model=model)
    started = time.time()
    rows: list[dict] = []
    tokens_in = tokens_out = 0
    usage_seen = False
    model_used: str | None = None

    for pdf in pdfs:
        row: dict = {
            "file": pdf.name,
            "path": str(pdf),
            "error": None,
            "no_text_layer": False,
            "verdicts": {},
            "fields": {name: None for name in CORE_FIELDS},
            "flags": [],
            "status": "ok",
        }
        try:
            text = extract_pdf_text(pdf)
            if not text.strip():
                row["no_text_layer"] = True
            else:
                result = brain.extract(text)
                model_used = result.model or model_used
                usage = result.usage
                if isinstance(usage, dict):
                    usage_seen = True
                    tokens_in += int(usage.get("prompt_tokens") or 0)
                    tokens_out += int(usage.get("completion_tokens") or 0)
                source_norm = normalize_text(text)
                for name, field_value in result.extraction.core().items():
                    verdict = verify_field(name, field_value.value, field_value.quote, source_norm)
                    row["verdicts"][name] = verdict
                    row["fields"][name] = verdict.value
        except Exception as exc:  # noqa: BLE001 — one bad file must never kill the batch
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    anomalies, flags = analyze(rows, today=today)
    for row in rows:
        row["flags"] = sorted(set(flags.get(row["file"], [])))
        row["status"] = "flagged" if row["flags"] else "ok"

    ledger_path = out_dir / "ledger.csv"
    anomalies_path = out_dir / "anomalies.md"
    summary = {
        "input": str(input_dir),
        "files": len(pdfs),
        "ok": sum(1 for row in rows if row["status"] == "ok"),
        "flagged": sum(1 for row in rows if row["status"] == "flagged"),
        "anomalies": len(anomalies),
        "model": model_used,
        "tokens": {"input": tokens_in, "output": tokens_out} if usage_seen else None,
        "duration_s": round(time.time() - started, 1),
        "ledger": str(ledger_path),
        "anomalies_report": str(anomalies_path),
    }
    write_ledger(rows, ledger_path)
    write_anomalies_report(rows, anomalies, anomalies_path, summary)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
