"""Anomaly detection over ledger rows (all deterministic, all explainable)."""

from __future__ import annotations

from datetime import date

from .schema import CORE_FIELDS
from .verify import parse_date


def analyze(rows: list[dict], today: date | None = None) -> tuple[list[dict], dict[str, list[str]]]:
    """Return (anomalies, flags-per-file). Flags are short codes for the ledger."""
    # Business dates are local calendar dates by design; a tz-aware "today" is not meaningful here.
    today = today or date.today()  # noqa: DTZ011
    anomalies: list[dict] = []
    flags: dict[str, list[str]] = {}

    def add(filename: str, kind: str, detail: str, flag: str) -> None:
        anomalies.append({"file": filename, "kind": kind, "detail": detail})
        flags.setdefault(filename, []).append(flag)

    seen_invoice: dict[tuple[str, str], str] = {}
    for row in rows:
        filename = row.get("file", "?")
        if row.get("error"):
            add(filename, "EXTRACT_ERROR", row["error"], "EXTRACT_ERROR")
            continue
        if row.get("no_text_layer"):
            add(
                filename,
                "NO_TEXT_LAYER",
                "PDF has no extractable text (needs OCR before extraction)",
                "NO_TEXT_LAYER",
            )
        verdicts = row.get("verdicts") or {}
        for name in CORE_FIELDS:
            verdict = verdicts.get(name)
            if verdict is None:
                continue
            if verdict.status == "missing":
                add(filename, "MISSING_FIELD", f"{name}: not present in the document", f"MISSING:{name}")
            elif verdict.status == "unverified":
                add(
                    filename,
                    "UNVERIFIED_FIELD",
                    f"{name}={verdict.value!r} failed literalism ({verdict.reason}); quote: {verdict.quote!r}",
                    f"UNVERIFIED:{name}",
                )

        vendor = verdicts.get("vendor")
        number = verdicts.get("invoice_number")
        if vendor is not None and number is not None and vendor.value and number.value:
            key = (vendor.value.casefold().strip(), number.value.casefold().strip())
            if key in seen_invoice:
                other = seen_invoice[key]
                add(
                    filename,
                    "DUPLICATE_INVOICE",
                    f"same vendor+number as {other} ({vendor.value} / {number.value})",
                    f"DUPLICATE:{other}",
                )
                add(
                    other,
                    "DUPLICATE_INVOICE",
                    f"same vendor+number as {filename} ({vendor.value} / {number.value})",
                    f"DUPLICATE:{filename}",
                )
            else:
                seen_invoice[key] = filename

        due = verdicts.get("due_date")
        if due is not None and due.value:
            parsed = parse_date(due.value)
            if parsed is not None and parsed < today:
                add(filename, "OVERDUE", f"due date {parsed.isoformat()} is before {today.isoformat()}", "OVERDUE")

    return anomalies, flags
