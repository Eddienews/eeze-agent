"""E2 inbox tests — email parsing + pull logic against a fake IMAP (no network)."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from typing import ClassVar

import pytest

from eeze_agent.verticals.invoices import imap_source
from eeze_agent.verticals.invoices.imap_source import (
    ImapConfigError,
    _safe_name,
    pdf_attachments,
    pull_pdf_attachments,
)

PDF_BYTES = b"%PDF-1.4 fake invoice bytes"


def _mail_with_attachment() -> bytes:
    msg = EmailMessage()
    msg["From"] = "supplier@example.com"
    msg["To"] = "test@example.com"
    msg["Subject"] = "Your invoice"
    msg.set_content("Hi, invoice attached.")
    msg.add_attachment(PDF_BYTES, maintype="application", subtype="pdf", filename="fatura ção.pdf")
    return msg.as_bytes()


def _mail_without_attachment() -> bytes:
    msg = EmailMessage()
    msg["From"] = "friend@example.com"
    msg["Subject"] = "Welcome to Gmail"
    msg.set_content("No attachments here.")
    return msg.as_bytes()


def test_pdf_attachments_extraction():
    message = __import__("email").message_from_bytes(_mail_with_attachment())
    found = pdf_attachments(message)
    assert len(found) == 1
    name, payload = found[0]
    assert name == "fatura ção.pdf"
    assert payload == PDF_BYTES


def test_pdf_attachments_none():
    message = __import__("email").message_from_bytes(_mail_without_attachment())
    assert pdf_attachments(message) == []


def test_safe_name_sanitizes():
    assert _safe_name("../../evil name.pdf") == "evil name.pdf"
    assert _safe_name("no-extension") == "no-extension.pdf"
    assert _safe_name("weird<>:|?*name.pdf") == "weird_name.pdf"


class FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL; records the calls it received."""

    payloads: ClassVar[dict[int, bytes]] = {}

    def __init__(self, host: str, timeout: float | None = None):
        self.host = host
        self.logged: tuple[str, str] | None = None
        self.selected: tuple[str, bool] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user: str, password: str):
        self.logged = (user, password)
        return ("OK", [b"logged in"])

    def select(self, folder: str, readonly: bool = False):
        self.selected = (folder, readonly)
        return ("OK", [b"2"])

    def search(self, charset, *criteria):
        return ("OK", [b"1 2"])

    def fetch(self, message_id, spec):
        payload = self.payloads[int(message_id)]
        header = f"1 (BODY[] {{{len(payload)}}}".encode()
        return ("OK", [(header, payload), b")"])


def test_pull_end_to_end(tmp_path: Path, monkeypatch):
    FakeIMAP.payloads = {1: _mail_with_attachment(), 2: _mail_without_attachment()}
    monkeypatch.setattr(imap_source, "IMAP4_SSL", FakeIMAP)

    result = pull_pdf_attachments(tmp_path / "inbox", user="test@example.com", password="abcd efgh ijkl mnop")

    assert result.fetched == 2
    assert result.attachments == 1
    assert result.files[0].endswith("fatura ção.pdf")
    assert Path(result.files[0]).read_bytes() == PDF_BYTES
    assert any("no PDF attachment" in reason for reason in result.skipped)
    assert (tmp_path / "inbox" / "pull-summary.json").exists()


def test_pull_is_readonly(tmp_path: Path, monkeypatch):
    captured: dict = {}

    class RecordingIMAP(FakeIMAP):
        def select(self, folder: str, readonly: bool = False):
            captured["readonly"] = readonly
            return super().select(folder, readonly)
        def fetch(self, message_id, spec):
            captured["spec"] = spec
            return super().fetch(message_id, spec)

    RecordingIMAP.payloads = {1: _mail_with_attachment(), 2: _mail_without_attachment()}
    monkeypatch.setattr(imap_source, "IMAP4_SSL", RecordingIMAP)

    pull_pdf_attachments(tmp_path / "inbox", user="u", password="p")

    assert captured["readonly"] is True  # mailbox opened read-only
    assert "PEEK" in captured["spec"]  # never marks messages as seen


def test_pull_names_are_message_scoped_and_idempotent(tmp_path: Path, monkeypatch):
    """Re-pulling the same mailbox must not duplicate files; different messages with the
    same attachment name must not clash (each file carries its message id)."""
    FakeIMAP.payloads = {1: _mail_with_attachment(), 2: _mail_without_attachment()}
    monkeypatch.setattr(imap_source, "IMAP4_SSL", FakeIMAP)

    first = pull_pdf_attachments(tmp_path / "inbox", user="u", password="p")
    second = pull_pdf_attachments(tmp_path / "inbox", user="u", password="p")

    assert Path(first.files[0]).name == "1-fatura ção.pdf"
    assert second.files == first.files  # idempotent: same message -> same file
    pdfs = sorted((tmp_path / "inbox").glob("*.pdf"))
    assert len(pdfs) == 1  # no duplicate copies on disk


def test_pull_requires_credentials(tmp_path: Path, monkeypatch):
    for var in ("EEZE_IMAP_HOST", "EEZE_IMAP_USER", "EEZE_IMAP_APP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ImapConfigError):
        pull_pdf_attachments(tmp_path / "inbox")
