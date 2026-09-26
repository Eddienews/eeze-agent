"""Write-only local secret store (P2): the user's own provider keys, on this machine only.

Self-hosted and local-first: a key entered in Eeze is stored here and is only ever sent to the
provider the user chose. Deliberately NOT the settings DB — the DB is read by the UI/API layer,
while this file is written **through the API** and read only in-process: `provider_status` and
the HTTP surface report presence and `last4`, never a value. `get()` exists for IN-PROCESS use
(a brain building an `Authorization` header) and is documented as such.

File: ``<eeze home>/secrets.json`` — atomic replace; ``0600`` on POSIX (on Windows the file
inherits the user-profile ACL, the same protection the rest of ``~/.eeze`` has). A corrupt file
is quarantined (``secrets.json.bad-<ts>``) and treated as empty: a broken store must never crash
a run, and the old bytes must never be silently overwritten.

Names used by ``core/providers.py``:
``provider.<id>`` = API key · ``provider.<id>.base_url`` = endpoint override ·
``provider.<id>.models`` = JSON tier->model overrides · ``provider.default`` = default id.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SECRETS_FILE = "secrets.json"
SECRETS_ENV = "EEZE_SECRETS"  # full path to the store file (tests / alternate installs)
SHORT_VALUE_MAX = 8  # below this, `last4` reports "" — never half of a tiny secret
POSIX_MODE = 0o600


class SecretStore:
    """Write-only provider secrets. ``get`` is for in-process use only.

    Resolution: an explicit ``path`` wins, then an explicit ``home`` (``<home>/secrets.json``),
    then ``$EEZE_SECRETS`` (the file itself — how tests and alternate installs redirect it), then
    the operator's real ``~/.eeze``. ``home`` deliberately beats the env var so a caller that names
    a home always gets that home (the API passes its instance home).
    """

    def __init__(self, home: Path | None = None, path: Path | None = None) -> None:
        if path is None and home is None:
            override = (os.environ.get(SECRETS_ENV) or "").strip()
            if override:
                path = Path(override)
        if path is not None:
            self.path = Path(path)
            self.home = self.path.parent
            return
        self.home = Path(home) if home is not None else Path.home() / ".eeze"
        self.path = self.home / SECRETS_FILE

    # -- disk ------------------------------------------------------------------

    def _load(self) -> dict[str, str]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._quarantine()
            return {}
        if not isinstance(data, dict):
            self._quarantine()
            return {}
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}

    def _quarantine(self) -> None:
        stale = self.path.with_name(f"{self.path.name}.bad-{int(time.time())}")
        try:
            self.path.replace(stale)
        except OSError:
            pass

    def _save(self, data: dict[str, str]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        if os.name == "posix":
            os.chmod(tmp, POSIX_MODE)
        tmp.replace(self.path)

    # -- api -------------------------------------------------------------------

    def set(self, name: str, value: str) -> None:
        """Store ``value`` under ``name``. An empty/whitespace value is refused."""
        value = (value or "").strip()
        if not value:
            raise ValueError("refusing to store an empty secret")
        name = (name or "").strip()
        if not name:
            raise ValueError("refusing to store a secret without a name")
        data = self._load()
        data[name] = value
        self._save(data)

    def get(self, name: str) -> str | None:
        """IN-PROCESS ONLY — never expose a returned value through an HTTP surface."""
        return self._load().get(name)

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def last4(self, name: str) -> str:
        """Last 4 characters for display, or ``""`` when unset or too short to reveal safely."""
        value = self.get(name) or ""
        return value[-4:] if len(value) >= SHORT_VALUE_MAX else ""

    def delete(self, name: str) -> bool:
        data = self._load()
        if name not in data:
            return False
        del data[name]
        self._save(data)
        return True

    def names(self) -> list[str]:
        return sorted(self._load())
