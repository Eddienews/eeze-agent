"""Local state backup (F6): a single zip with the store, .env and (optionally) runs."""

from __future__ import annotations

import hashlib
import time
import zipfile
from pathlib import Path


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> bool:
    if not path.exists() or not path.is_file():
        return False
    zf.write(path, arcname)
    return True


def create_backup(
    *,
    repo_root: Path,
    home: Path | None = None,
    out_dir: Path | None = None,
    with_runs: bool = False,
) -> dict:
    """Zip the local state. Contains secrets (.env) — keep the archive safe, local-only."""
    home = home or Path.home() / ".eeze"
    out_dir = out_dir or repo_root / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"eeze-backup-{stamp}.zip"

    counts: dict[str, int] = {}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        n = 0
        # store (sqlite + WAL/SHM companions so the copy is consistent enough to restore)
        for name in ("eeze.db", "eeze.db-wal", "eeze.db-shm"):
            if _add_file(zf, home / name, f"eeze/{name}"):
                n += 1
        counts["state"] = n

        n = 0
        for pattern in ("resume-*.log", "routines"):
            for path in sorted(home.glob(pattern)):
                if path.is_file():
                    if _add_file(zf, path, f"eeze/{path.name}"):
                        n += 1
                elif path.is_dir():
                    for sub in sorted(path.rglob("*")):
                        if sub.is_file() and _add_file(zf, sub, f"eeze/{path.name}/{sub.relative_to(path)}"):
                            n += 1
        counts["logs"] = n

        counts["env"] = 1 if _add_file(zf, repo_root / ".env", "env/.env") else 0

        if with_runs:
            n = 0
            for base in ("runs", "routines", "audits"):
                root = repo_root / "artifacts" / base
                if root.exists():
                    for path in sorted(root.rglob("*")):
                        if path.is_file() and _add_file(zf, path, f"artifacts/{base}/{path.relative_to(root)}"):
                            n += 1
            counts["artifacts"] = n

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return {
        "archive": str(archive),
        "bytes": archive.stat().st_size,
        "sha256": digest,
        "counts": counts,
        "with_runs": with_runs,
        "note": "contains secrets (.env) — store it somewhere safe; local-only",
    }
