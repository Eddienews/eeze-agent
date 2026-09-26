"""Literalism verification.

The rule of this vertical: every value written to the ledger must exist inside a
verbatim quote that is found in the source text. Anything else is flagged — never
silently accepted, never invented, never ``0`` for a missing field.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from .schema import FieldVerdict

_MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTHS = {name: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTHS_ABBR = {name[:3]: i for i, name in enumerate(_MONTH_NAMES, start=1)}
_MONTHS.update(_MONTHS_ABBR)

_CURRENCY_ALIASES: dict[str, str] = {
    "€": "EUR",
    "eur": "EUR",
    "$": "USD",
    "usd": "USD",
    "r$": "BRL",
    "brl": "BRL",
    "£": "GBP",
    "gbp": "GBP",
}

_NUM_RE = re.compile(r"[-+]?\d[\d\s\u00a0.,]*")

_PDF_QUOTE_FIXUPS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "\u00a0": " "})


def normalize_text(value: str) -> str:
    """Loose normalization for containment checks (never for display)."""
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(_PDF_QUOTE_FIXUPS)
    value = re.sub(r"\s+", " ", value)
    return value.casefold().strip()


def parse_amount(value: str | None) -> float | None:
    """Best-effort numeric read of an amount as written (1.234,50 == 1234.50)."""
    if not value:
        return None
    match = _NUM_RE.search(value.replace("\u00a0", " "))
    if not match:
        return None
    token = match.group(0).strip().replace(" ", "")
    last_dot, last_comma = token.rfind("."), token.rfind(",")
    decimal_pos = max(last_dot, last_comma)
    if decimal_pos == -1:
        cleaned = token
    else:
        decimal_sep = token[decimal_pos]
        other = "," if decimal_sep == "." else "."
        digits_after = len(token) - decimal_pos - 1
        if token.count(decimal_sep) == 1 and digits_after in (1, 2):
            cleaned = token.replace(other, "").replace(decimal_sep, ".")
        elif digits_after == 3 and other not in token:
            cleaned = token.replace(decimal_sep, "")
        else:
            cleaned = token.replace(other, "").replace(decimal_sep, ".")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    """Parse the common date spellings found on invoices."""
    if not value:
        return None
    text = normalize_text(value).replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            # Business dates on invoices are naive calendar dates by design.
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    # "march 3 2026" / "3 march 2026" (month names, full or abbreviated)
    parts = text.split()
    if len(parts) == 3:
        day = month = year = None
        for part in parts:
            if month is None and part in _MONTHS:
                month = _MONTHS[part]
            elif day is None and part.isdigit() and len(part) <= 2:
                day = int(part)
            elif year is None and part.isdigit() and len(part) == 4:
                year = int(part)
        if day and month and year:
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _date_literals(value: str) -> list[str]:
    """Literal spellings the same date could take in the source text."""
    day = parse_date(value)
    if day is None:
        return [normalize_text(value)]
    month_name = _MONTH_NAMES[day.month - 1]
    return [
        f"{day.year:04d}-{day.month:02d}-{day.day:02d}",
        f"{day.day:02d}/{day.month:02d}/{day.year:04d}",
        f"{day.day}/{day.month}/{day.year}",
        f"{day.day:02d}.{day.month:02d}.{day.year:04d}",
        f"{day.day:02d}-{day.month:02d}-{day.year:04d}",
        f"{month_name} {day.day}, {day.year}",
        f"{month_name} {day.day} {day.year}",
        f"{day.day} {month_name} {day.year}",
        f"{day.day} {month_name[:3]} {day.year}",
        f"{month_name[:3]} {day.day}, {day.year}",
    ]


def _amount_matches(value: str, quote: str) -> bool:
    left, right = parse_amount(value), parse_amount(quote)
    if left is not None and right is not None:
        return abs(left - right) < 0.005
    return normalize_text(value) in normalize_text(quote)


def _date_matches(value: str, quote: str) -> bool:
    quote_norm = normalize_text(quote)
    return any(normalize_text(candidate) in quote_norm for candidate in _date_literals(value))


def _currency_matches(value: str, quote: str) -> bool:
    wanted = _CURRENCY_ALIASES.get(normalize_text(value), normalize_text(value))
    quote_norm = normalize_text(quote)
    return any(
        _CURRENCY_ALIASES[alias] == wanted and alias in quote_norm for alias in _CURRENCY_ALIASES
    ) or (wanted in quote_norm)


def currency_iso(value: str | None) -> str | None:
    """Map a currency as written (symbol or ISO) to its ISO 4217 code."""
    if not value:
        return None
    alias = _CURRENCY_ALIASES.get(normalize_text(value))
    if alias:
        return alias
    upper = value.strip().upper()
    return upper if len(upper) == 3 and upper.isalpha() else None


def verify_field(field: str, value: str | None, quote: str | None, source_norm: str) -> FieldVerdict:
    """Check one field against the source text. ``source_norm`` must be ``normalize_text``d.

    The contract with the brain is quote-based: a value is trusted only when it can be
    located inside a verbatim quote, and that quote itself must exist in the document.
    """
    value = value.strip() if isinstance(value, str) else value
    quote = quote if isinstance(quote, str) else None

    if not value and not quote:
        return FieldVerdict(field=field, value=None, status="missing", reason="field_absent")
    if not quote:
        return FieldVerdict(
            field=field, value=value, status="unverified", reason="no_quote", quote=None
        )
    quote_norm = normalize_text(quote)
    if not quote_norm or quote_norm not in source_norm:
        return FieldVerdict(
            field=field, value=value, status="unverified", reason="quote_not_in_source", quote=quote
        )
    if not value:
        return FieldVerdict(field=field, value=None, status="missing", reason="value_absent", quote=quote)

    if field == "total_amount":
        ok = _amount_matches(value, quote)
    elif field in ("issue_date", "due_date"):
        ok = _date_matches(value, quote)
    elif field == "currency":
        ok = _currency_matches(value, quote)
    else:
        ok = normalize_text(value) in quote_norm

    if ok:
        return FieldVerdict(field=field, value=value, status="verified", quote=quote)
    return FieldVerdict(
        field=field, value=value, status="unverified", reason="value_not_in_quote", quote=quote
    )
