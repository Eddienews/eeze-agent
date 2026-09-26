"""Invoice vertical — data model for extracted fields and verification verdicts."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field as PydanticField

CORE_FIELDS: tuple[str, ...] = (
    "vendor",
    "invoice_number",
    "issue_date",
    "due_date",
    "total_amount",
    "currency",
)


class FieldValue(BaseModel):
    """One extracted field: literal value plus its verbatim source quote."""

    value: str | None = None
    quote: str | None = None


class InvoiceExtraction(BaseModel):
    """Brain output for a single invoice document."""

    fields: dict[str, FieldValue] = PydanticField(default_factory=dict)

    def core(self) -> dict[str, FieldValue]:
        """Every core field, defaulting to empty when the brain omitted it."""
        return {name: self.fields.get(name, FieldValue()) for name in CORE_FIELDS}


class FieldVerdict(BaseModel):
    """Outcome of the literalism check for one field.

    status:
      - ``verified``   — value found inside a quote that exists verbatim in the source
      - ``unverified`` — value/quote present but failed the literalism check (flagged)
      - ``missing``    — field not present in the document (quote and value empty)
    """

    field: str
    value: str | None = None
    status: str = "missing"
    reason: str | None = None
    quote: str | None = None


__all__ = ["CORE_FIELDS", "FieldValue", "FieldVerdict", "InvoiceExtraction"]
