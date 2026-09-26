# ADR-0004 — No AGPL in the engine: PyMuPDF replaced by pypdf

Date: 2026-09-23 · Status: accepted

## Context

F6 checklist item 10 flagged `PyMuPDF` (**AGPL-3.0** or commercial) as incompatible with the
planned permissive (Apache-2.0) engine distribution. It was used in exactly one place for text
extraction, plus the invoice test fixtures.

## Decision

The runtime dependency is **`pypdf` (BSD-3-Clause, pure Python)** — `verticals/invoices/pipeline.py`
and `pyproject.toml`; the test suite now authors its fixture PDFs with a small stdlib writer so no
AGPL tool is needed for the suite either. `pdfminer.six` remains the fallback if layout fidelity
ever becomes a problem; a real OCR path (for scanned invoices) would live in a separate, explicitly
licensed module.

## Evidence (A/B on the 5 real invoice PDFs, same extractor model `hermes-agent`)

- Extracted characters: pypdf 207/148/160/207/0 vs PyMuPDF 208/149/161/208/0 (1 char less per
  text PDF — trailing whitespace; the image-only file stays 0).
- Full vertical re-run: **ledger identical in all 11 columns × 5 rows** (vendors, numbers, dates,
  amounts, currencies, statuses, the `DUPLICATE:41-2026-0101_acme.pdf` flag) and identical anomaly
  categories (1 ok / 4 flagged / 4 anomalies).
- Suite: invoice tests 15/15 with the stdlib PDF fixtures.

## Consequences

- The engine's dependency set is permissive end to end; F6 item 10 is resolved.
- Rule going forward: a copyleft dependency must be replaced or isolated *before* the OSS split,
  never shipped in the permissive distribution by accident.
