"""Read-only IMAP source (E2): pull PDF attachments from a mailbox into a local folder.

Strictly read-only: the mailbox is opened `readonly=True` and message bodies are
fetched with `BODY.PEEK[]`, so no message is ever marked as seen, moved, or deleted.
Credentials come from the environment (`.env`), never from code or chat:

    EEZE_IMAP_HOST          (default: imap.gmail.com)
    EEZE_IMAP_USER          the mailbox address
    EEZE_IMAP_APP_PASSWORD  the app password (spaces are tolerated)
"""

from __future__ import annotations

import email
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from email.message import Message
from imaplib import IMAP4_SSL
from pathlib import Path

DEFAULT_HOST = "imap.gmail.com"


class ImapConfigError(RuntimeError):
    """Missing credentials (.env not filled)."""


class ImapError(RuntimeError):
    """Connection / authentication / folder problems."""


@dataclass
class PullResult:
    host: str
    folder: str
    search: str
    fetched: int
    attachments: int
    files: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    at: str = ""


def _credentials(host: str | None, user: str | None, password: str | None) -> tuple[str, str, str]:
    host = host or os.environ.get("EEZE_IMAP_HOST") or DEFAULT_HOST
    user = user or os.environ.get("EEZE_IMAP_USER")
    password = password or os.environ.get("EEZE_IMAP_APP_PASSWORD")
    if not user or not password:
        raise ImapConfigError(
            "EEZE_IMAP_USER / EEZE_IMAP_APP_PASSWORD not set — fill them in .env (they never go through chat)"
        )
    # Google shows app passwords with spaces; the login expects them without.
    return host, user, password.replace(" ", "")


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w.\- ]+", "_", name.replace("\\", "/").split("/")[-1]).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or cleaned.lower() == ".pdf":
        return "attachment.pdf"
    return cleaned if cleaned.lower().endswith(".pdf") else f"{cleaned}.pdf"


def test_login(host: str, user: str, password: str, folder: str = "INBOX") -> dict:
    """Probe a mailbox with explicit credentials (F5 wizard). Raises ImapError on failure.

    Returns a small dict (folder + message count) — never the password.
    """
    host = host.strip() or DEFAULT_HOST
    user = user.strip()
    password = password.replace(" ", "")
    try:
        with IMAP4_SSL(host, timeout=20) as conn:
            conn.login(user, password)
            typ, data = conn.select(f'"{folder}"' if " " in folder else folder, readonly=True)
            if typ != "OK":
                raise ImapError(f"cannot open folder {folder!r}")
            try:
                count = int(data[0])
            except (TypeError, ValueError):
                count = -1
            conn.close()
    except ImapError:
        raise
    except Exception as exc:
        raise ImapError(f"{type(exc).__name__}: {exc}") from exc
    return {"host": host, "folder": folder, "messages": count}


def pdf_attachments(message: Message) -> list[tuple[str, bytes]]:
    """All PDF attachments of a parsed message, in order."""
    out: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = part.get_filename() or ""
        content_type = part.get_content_type()
        if not name.lower().endswith(".pdf") and content_type != "application/pdf":
            continue
        payload = part.get_payload(decode=True) or b""
        if payload:
            out.append((name or "attachment.pdf", payload))
    return out


DEFAULT_PULL_LIMIT = 500


def validate_search(search: str) -> str:
    """Refuse IMAP search strings that could carry a second command.

    imaplib does not reject CR/LF: ``ALL\r\nA1 STORE 1:* +FLAGS (\\Deleted)`` would have run a
    write on a mailbox this module promises to open read-only. Literals (``{n}``) are refused
    too; a search is criteria, nothing more.
    """
    text = str(search or "ALL").strip() or "ALL"
    if len(text) > 500 or any(ord(ch) < 32 or ord(ch) == 127 or ch in "{}" for ch in text):
        raise ImapConfigError("invalid IMAP search (control characters or literals are not allowed)")
    return text


def pull_pdf_attachments(
    out_dir: Path,
    folder: str = "INBOX",
    search: str = "ALL",
    limit: int | None = DEFAULT_PULL_LIMIT,
    host: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> PullResult:
    """Download every PDF attachment of the matching messages into ``out_dir``.

    ``limit`` keeps only the most recent N matching messages. Files are never
    overwritten: a name collision gets the message id as prefix.
    """
    host, user, password = _credentials(host, user, password)
    search = validate_search(search)
    if any(ord(ch) < 32 for ch in folder):
        raise ImapConfigError("invalid IMAP folder name")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    skipped: list[str] = []
    fetched = 0

    try:
        with IMAP4_SSL(host, timeout=60) as imap:
            imap.login(user, password)
            status, _ = imap.select(f'"{folder}"' if " " in folder else folder, readonly=True)
            if status != "OK":
                raise ImapError(f"cannot open folder {folder!r}")
            status, data = imap.search(None, search)
            if status != "OK":
                raise ImapError(f"search failed: {search!r}")
            message_ids = data[0].split() if data and data[0] else []
            if limit is not None:
                message_ids = message_ids[-limit:]
            for message_id in message_ids:
                status, parts = imap.fetch(message_id, "(BODY.PEEK[])")
                if status != "OK":
                    skipped.append(f"message {message_id!r}: fetch failed")
                    continue
                raw = None
                for item in parts or []:
                    if isinstance(item, tuple) and isinstance(item[1], (bytes, bytearray)):
                        raw = bytes(item[1])
                        break
                if raw is None:
                    skipped.append(f"message {message_id!r}: empty fetch")
                    continue
                fetched += 1
                attachments = pdf_attachments(email.message_from_bytes(raw))
                if not attachments:
                    skipped.append(f"message {message_id!r}: no PDF attachment")
                    continue
                prefix = message_id.decode() if isinstance(message_id, bytes) else str(message_id)
                for index, (name, payload) in enumerate(attachments, start=1):
                    # Two same-named PDFs in one message used to overwrite each other.
                    stem = f"{prefix}-{index}-{_safe_name(name)}" if len(attachments) > 1 \
                        else f"{prefix}-{_safe_name(name)}"
                    target = out_dir / stem  # message-scoped: a re-pull rewrites the same file
                    target.write_bytes(payload)
                    files.append(str(target))
    except ImapError:
        raise
    except Exception as exc:  # imaplib raises IMAP4.error / OSError — surface a readable message
        raise ImapError(f"{type(exc).__name__}: {exc}") from exc

    result = PullResult(
        host=host,
        folder=folder,
        search=search,
        fetched=fetched,
        attachments=len(files),
        files=files,
        skipped=skipped,
        at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    (out_dir / "pull-summary.json").write_text(
        json.dumps(asdict(result), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result
