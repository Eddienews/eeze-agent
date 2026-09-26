"""Ledger + anomaly report writers (CSV and Markdown)."""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import CORE_FIELDS
from .verify import currency_iso, parse_date

CSV_COLUMNS = [
    "file",
    *CORE_FIELDS,
    "due_date_iso",
    "currency_iso",
    "status",
    "flags",
]


def write_ledger(rows: list[dict], path: Path) -> None:
    """Deterministic CSV: ordered by parsed due date (unparseable last), then file name.

    Literal values are kept exactly as written; ``*_iso`` columns carry the derived
    machine-readable form (empty when the value cannot be parsed — never guessed).
    """

    def sort_key(row: dict) -> tuple[str, str]:
        due = (row.get("fields") or {}).get("due_date")
        parsed = parse_date(due) if due else None
        return (parsed.isoformat() if parsed else "9999-12-31", row["file"])

    ordered = sorted(rows, key=sort_key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            fields = row.get("fields") or {}
            due = fields.get("due_date")
            parsed_due = parse_date(due) if due else None
            writer.writerow(
                {
                    "file": row["file"],
                    **{name: fields.get(name) if fields.get(name) is not None else "" for name in CORE_FIELDS},
                    "due_date_iso": parsed_due.isoformat() if parsed_due else "",
                    "currency_iso": currency_iso(fields.get("currency")) or "",
                    "status": row.get("status", "ok"),
                    "flags": "; ".join(row.get("flags") or []),
                }
            )


def write_anomalies_report(
    rows: list[dict], anomalies: list[dict], path: Path, summary: dict
) -> None:
    """Human-readable anomaly report, grouped by kind, with details."""
    by_kind: dict[str, list[dict]] = {}
    for anomaly in anomalies:
        by_kind.setdefault(anomaly["kind"], []).append(anomaly)

    lines: list[str] = []
    lines.append("# Invoice ledger — anomaly report")
    lines.append("")
    lines.append(
        f"Processed **{summary.get('files', 0)}** files · "
        f"ok **{summary.get('ok', 0)}** · flagged **{summary.get('flagged', 0)}** · "
        f"anomalies **{len(anomalies)}**"
    )
    lines.append("")
    lines.append(
        f"Model: `{summary.get('model') or 'unavailable'}` · "
        f"tokens: in {summary.get('tokens', {}).get('input') if summary.get('tokens') else None} / "
        f"out {summary.get('tokens', {}).get('output') if summary.get('tokens') else None} · "
        f"{(summary.get('duration_s') or 0):.1f}s"
    )
    lines.append("")

    if not anomalies:
        lines.append("No anomalies detected. Every value in the ledger is verified against a verbatim quote.")
    for kind in sorted(by_kind):
        lines.append(f"## {kind} ({len(by_kind[kind])})")
        lines.append("")
        for anomaly in by_kind[kind]:
            lines.append(f"- `{anomaly['file']}` — {anomaly['detail']}")
        lines.append("")

    flagged_rows = [row for row in rows if row.get("status") == "flagged"]
    if flagged_rows:
        lines.append("## Files in the ledger")
        lines.append("")
        lines.append("| file | status | flags |")
        lines.append("| --- | --- | --- |")
        for row in flagged_rows:
            lines.append(f"| `{row['file']}` | {row['status']} | {', '.join(row.get('flags') or [])} |")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
