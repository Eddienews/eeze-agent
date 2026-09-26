"""Extraction brain client (OpenAI-compatible).

Defaults to the local Hermes gateway — local-first: the user's own brain, no
third-party SaaS required. Any OpenAI-compatible endpoint works via
``EEZE_EXTRACT_BASE_URL`` / ``EEZE_EXTRACT_API_KEY`` / ``EEZE_EXTRACT_MODEL``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from .schema import CORE_FIELDS, FieldValue, InvoiceExtraction

DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_MODEL = "hermes-agent"

SYSTEM_PROMPT = """You extract invoice fields from plain text (OCR/PDF extraction output).

Return ONLY a JSON object with this exact shape:
{"fields": {"vendor": {"value": ..., "quote": ...}, "invoice_number": {...}, "issue_date": {...}, "due_date": {...}, "total_amount": {...}, "currency": {...}}}

Rules (non-negotiable):
1. "quote" MUST be a verbatim substring copied EXACTLY from the input text (copy-paste, no edits, no paraphrase). The quote is how downstream verification locates the value.
2. "value" is the normalized field as written in the quote, in the SAME order/format used in the quote (e.g. quote "Total Due: EUR 3.499,00" -> value "3.499,00" for total_amount and "EUR" for currency).
3. If a field is NOT present in the text, use {"value": null, "quote": null}. NEVER guess, compute, translate, or invent. A missing field is a valid answer.
4. total_amount = the grand total / amount due, NOT the subtotal and NOT the tax line. currency = the currency actually shown (ISO code or symbol).
5. amounts and dates stay as written (do not convert separators or formats).
6. No markdown, no commentary — output the JSON object only."""

USER_TEMPLATE = "Invoice text:\n---\n{text}\n---"

MAX_TEXT_CHARS = 12_000


class ExtractionError(RuntimeError):
    """Raised when the brain cannot produce parseable JSON."""


@dataclass
class BrainResult:
    extraction: InvoiceExtraction
    usage: dict | None = None
    model: str | None = None


def _first_json_object(text: str) -> str | None:
    """Extract the first balanced {...} block from a possibly chatty reply."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


class ExtractionBrain:
    """Thin OpenAI-compatible chat client used for invoice extraction."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("EEZE_EXTRACT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("EEZE_EXTRACT_API_KEY") or ""
        self.model = model or os.environ.get("EEZE_EXTRACT_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.budget_agent: object | None = None  # whose daily cap pays (routine sets it)

    def extract(self, text: str) -> BrainResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TEMPLATE.format(text=text[:MAX_TEXT_CHARS])},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        from eeze_agent.core import spend

        try:
            spend.check_budget(self.budget_agent)
        except spend.BudgetExceeded as exc:
            raise ExtractionError(str(exc)) from exc
        response = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
        )
        if response.status_code != 200:
            raise ExtractionError(f"brain HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        try:
            usage = body.get("usage") or {}
            spend.record(getattr(self.budget_agent, "id", "default"), self.model,
                         int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0),
                         source="invoices")
        except Exception:  # noqa: BLE001, S110 — bookkeeping never blocks extraction
            pass
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionError(f"brain reply missing choices: {str(body)[:300]}") from exc

        raw = _first_json_object(content or "")
        if raw is None:
            raise ExtractionError(f"no JSON object in brain reply: {(content or '')[:300]}")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"invalid JSON from brain: {exc}") from exc

        fields_raw = parsed.get("fields") if isinstance(parsed, dict) else None
        if not isinstance(fields_raw, dict):
            raise ExtractionError(f"brain reply lacks 'fields': {raw[:300]}")
        fields: dict[str, FieldValue] = {}
        for name in CORE_FIELDS:
            item = fields_raw.get(name)
            if isinstance(item, dict):
                value = item.get("value")
                quote = item.get("quote")
                fields[name] = FieldValue(
                    value=str(value).strip() if value is not None else None,
                    quote=str(quote) if quote is not None else None,
                )
            else:
                fields[name] = FieldValue()
        return BrainResult(
            extraction=InvoiceExtraction(fields=fields),
            usage=body.get("usage"),
            model=body.get("model") or self.model,
        )
