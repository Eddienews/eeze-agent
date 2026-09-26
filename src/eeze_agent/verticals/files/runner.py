"""Plan (preview), apply and undo for the files vertical.

Safety rules, all enforced here:
- only files DIRECTLY inside the chosen folder are touched (no recursion, no other folder);
  hidden/system files (desktop.ini, Thumbs.db, ~$ lock files, dotfiles) are never touched;
- a preview is computed first and any conflict (a target name already taken by something
  that is not part of the batch, or two files wanting the same name) refuses the whole batch;
- nothing is ever overwritten or deleted — duplicates are only reported; every move uses a
  rename that FAILS if the target exists (never a replace);
- renames go through temporary names that still carry the original name
  (``.eeze-tmp-<tag>-<i>--<original>``), so chains/swaps (img2 -> img1 -> ...) work and a
  file is recoverable by eye even after a power cut;
- the undo log is written BEFORE the first move, so an interrupted batch can still be undone:
  :func:`undo` finds each file under its new name, its temporary name or its original name.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime
from pathlib import Path

from .exif import date_taken
from .spec import IMAGE_EXTS, VIDEO_EXTS, FilesSpec

REPORT_NAME = "files-report.json"
MAX_FILES = 5000
TMP_PREFIX = ".eeze-tmp-"
_SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", "folder.jpg", "albumart.jpg"}


class FilesError(RuntimeError):
    pass


def _is_hidden_or_system(path: Path) -> bool:
    name = path.name.lower()
    if name in _SKIP_NAMES or name.startswith(("~$", ".")):
        return True
    attrs = getattr(path.stat(), "st_file_attributes", 0)  # Windows only
    return bool(attrs & (getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
                         | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)))


def _mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)  # noqa: DTZ006 — local wall clock
    except (OSError, OverflowError, ValueError):  # pre-1970 stamps raise on Windows
        return datetime(1970, 1, 1)  # noqa: DTZ001


def _when(path: Path, prefer_taken: bool) -> datetime:
    if prefer_taken and path.suffix.lower() in {".jpg", ".jpeg"}:
        taken = date_taken(path)
        if taken is not None:
            return taken
    return _mtime(path)


def _selected(spec: FilesSpec) -> list[Path]:
    folder = spec.folder_path()
    if not folder.is_dir():
        raise FilesError(f"folder not found: {folder}")
    exts = spec.extensions()
    files = [p for p in folder.iterdir()
             if p.is_file() and not p.is_symlink() and not _is_hidden_or_system(p)
             and (exts is None or p.suffix.lower() in exts)]
    if len(files) > MAX_FILES:
        raise FilesError(f"{len(files)} files — more than {MAX_FILES}; pick a smaller folder")
    if spec.order == "taken":
        files.sort(key=lambda p: (_when(p, True), _natural_key(p.name)))
    elif spec.order == "modified":
        files.sort(key=lambda p: (_mtime(p), _natural_key(p.name)))
    else:
        files.sort(key=lambda p: _natural_key(p.name))
    return files


def _natural_key(name: str) -> list:
    """img2 before img10 — the order people expect."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _format(pattern: str, *, n: int, when: datetime, stem: str) -> str:
    def repl(match: re.Match) -> str:
        token = match.group(1)
        if token.startswith("n"):
            width = int(token.split(":")[1]) if ":" in token else 0
            return str(n).zfill(width)
        if token == "date":
            return when.strftime("%Y-%m-%d")
        if token == "time":
            return when.strftime("%H%M%S")
        if token == "name":
            return stem
        return ""

    return re.sub(r"\{(n(?::0?\d)?|date|time|name|ext)\}", repl, pattern)


def _organize_key(spec: FilesSpec, path: Path) -> str:
    if spec.by == "type":
        ext = path.suffix.lower()
        return "Images" if ext in IMAGE_EXTS else "Videos" if ext in VIDEO_EXTS else "Other"
    when = _when(path, True)
    return when.strftime({"year": "%Y", "month": "%Y-%m", "day": "%Y-%m-%d"}[spec.by])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_changes(spec: FilesSpec) -> dict:
    """What WOULD happen — nothing is touched. ``changes`` use names relative to the folder."""
    folder = spec.folder_path()
    files = _selected(spec)
    out: dict = {"op": spec.op, "folder": str(folder), "files": len(files),
                 "changes": [], "conflicts": [], "duplicates": []}
    if spec.op == "duplicates":
        by_size: dict[int, list[Path]] = {}
        for path in files:
            by_size.setdefault(path.stat().st_size, []).append(path)
        for group in by_size.values():
            if len(group) < 2:
                continue
            by_hash: dict[str, list[str]] = {}
            for path in group:
                by_hash.setdefault(_sha256(path), []).append(path.name)
            out["duplicates"] += [sorted(names) for names in by_hash.values() if len(names) > 1]
        return out

    sources = {p.name.lower() for p in files}
    existing = {p.name.lower() for p in folder.iterdir()}
    targets: dict[str, str] = {}
    for index, path in enumerate(files):
        if spec.op == "rename":
            stem = _format(spec.pattern or "", n=spec.start + index,
                           when=_when(path, spec.order == "taken"), stem=path.stem)
            new = f"{stem}{path.suffix}"
        else:  # organize
            key = _organize_key(spec, path)
            sub = folder / key
            if sub.exists() and (sub.is_symlink() or not sub.is_dir()
                                 or sub.resolve().parent != folder.resolve()):
                out["conflicts"].append(f"{key} exists but is not a normal sub-folder")
                continue
            new = f"{key}/{path.name}"
        if new == path.name:
            continue
        if len(str(folder / new)) > 255:
            out["conflicts"].append(f"{new}: the full path would be too long for Windows")
            continue
        low = new.lower()
        if low in targets:
            out["conflicts"].append(f"{path.name} and {targets[low]} would both become {new}")
            continue
        targets[low] = path.name
        if spec.op == "rename" and low in existing and low not in sources:
            out["conflicts"].append(f"{new} already exists in the folder (it is not part of this batch)")
        if spec.op == "organize" and (folder / new).exists():
            out["conflicts"].append(f"{new} already exists")
        out["changes"].append({"from": path.name, "to": new})
    return out


def _move(src: Path, dst: Path) -> None:
    """Rename that never overwrites: Windows ``os.rename`` already fails on an existing
    target; elsewhere check first (``os.replace`` is never used)."""
    if os.name != "nt" and (dst.exists() or dst.is_symlink()):
        raise FileExistsError(f"refusing to overwrite {dst}")
    os.rename(src, dst)


def _tmp_name(tag: str, index: int, original: str) -> str:
    return f"{TMP_PREFIX}{tag}-{index}--{original}"


def _write_report(out_dir: Path, report: dict) -> None:
    path = out_dir / REPORT_NAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # our own report file, never a user file


def _run_moves(folder: Path, moves: list[dict]) -> list[str]:
    """Execute ``[{from, tmp, to}]`` in two phases. On failure roll back EVERYTHING in two
    phases too (placed -> temporary -> original), collecting per-file errors instead of
    stopping. Returns the rollback problems (empty when rolled back cleanly)."""
    staged: list[dict] = []
    placed: list[dict] = []
    try:
        for move in moves:
            _move(folder / move["from"], folder / move["tmp"])
            staged.append(move)
        for move in moves:
            target = folder / move["to"]
            target.parent.mkdir(parents=True, exist_ok=True)
            _move(folder / move["tmp"], target)
            placed.append(move)
        return []
    except Exception as exc:
        problems: list[str] = []
        for move in reversed(placed):  # phase 1: new name -> temporary name
            try:
                _move(folder / move["to"], folder / move["tmp"])
            except OSError as err:
                problems.append(f"{move['to']}: {err}")
        for move in staged:  # phase 2: temporary name -> original name
            try:
                if (folder / move["tmp"]).exists():
                    _move(folder / move["tmp"], folder / move["from"])
            except OSError as err:
                problems.append(f"{move['tmp']}: {err}")
        raise FilesError(f"stopped: {exc}"
                         + (f" — could not restore: {'; '.join(problems[:5])}" if problems else
                            " — every file was put back")) from exc


def apply_plan(spec: FilesSpec, out_dir: str | Path) -> dict:
    """Apply the plan (after approval). Refuses on any conflict; writes report + undo log
    BEFORE touching anything, so even an interrupted batch can be undone."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_changes(spec)
    folder = spec.folder_path()
    report = {**plan, "applied": 0, "undone": False, "status": "planned",
              "at": datetime.now().replace(microsecond=0).isoformat()}  # noqa: DTZ005
    if plan["conflicts"]:
        report.update(status="refused", error="conflicts — nothing was changed")
        _write_report(out_dir, report)
        raise FilesError("; ".join(plan["conflicts"][:5]))
    tag = uuid.uuid4().hex[:8]
    moves = [{"from": c["from"], "to": c["to"], "tmp": _tmp_name(tag, i, c["from"])}
             for i, c in enumerate(plan["changes"])]
    new_dirs = sorted({str(Path(m["to"]).parent) for m in moves
                       if str(Path(m["to"]).parent) != "." and not (folder / Path(m["to"]).parent).exists()})
    report.update(status="applying", moves=moves, created_dirs=new_dirs,
                  undo=[{"from": m["to"], "to": m["from"], "tmp": m["tmp"]} for m in moves])
    _write_report(out_dir, report)  # the undo log exists before the first move
    try:
        _run_moves(folder, moves)
    except FilesError as exc:
        report.update(status="rolled_back", error=str(exc), applied=0)
        _write_report(out_dir, report)
        raise
    missing = [m["to"] for m in moves if not (folder / m["to"]).exists()]
    report.update(status="applied" if not missing else "partial", applied=len(moves) - len(missing))
    _write_report(out_dir, report)
    if missing:
        raise FilesError(f"verification failed: {missing[:3]} not found after the change")
    return report


def undo(report_path: str | Path) -> dict:
    """Put every file back under its original name.

    Works for finished batches and for batches interrupted mid-way (each file is looked up
    under its new name, then its temporary name). Refuses — touching nothing — if anything
    is ambiguous: a file is missing, or an original name is taken by something else.
    """
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("undone"):
        raise FilesError("this change was already undone")
    folder = Path(report["folder"])
    entries = report.get("undo") or []
    new_names = {str(e["from"]).lower() for e in entries}
    plan: list[tuple[str, str]] = []
    problems: list[str] = []
    for entry in entries:
        new, old, tmp = entry["from"], entry["to"], entry.get("tmp")
        if (folder / new).exists():
            current = new
        elif tmp and (folder / tmp).exists():
            current = tmp
        elif (folder / old).exists() and old.lower() not in new_names:
            continue  # this one never moved (interrupted before it) — already original
        else:
            problems.append(f"{new} is missing")
            continue
        # An original name that is also one of the batch's new names (renumbering p2 -> p1,
        # p3 -> p2) or differs only by case is freed by the batch itself — not a conflict.
        if (folder / old).exists() and old.lower() not in new_names and old.lower() != current.lower():
            problems.append(f"{old} exists again")
            continue
        plan.append((current, old))
    if problems:
        raise FilesError("cannot undo safely: " + "; ".join(problems[:5]))
    if plan:
        tag = uuid.uuid4().hex[:8]
        _run_moves(folder, [{"from": cur, "to": old, "tmp": _tmp_name(tag, i, old)}
                            for i, (cur, old) in enumerate(plan)])
    for rel in report.get("created_dirs") or []:  # only folders this batch created
        sub = folder / rel
        try:
            if sub.is_dir() and not sub.is_symlink() and not any(sub.iterdir()):
                sub.rmdir()
        except OSError:
            pass
    report["undone"] = True
    report["status"] = "undone"
    report["undone_at"] = datetime.now().replace(microsecond=0).isoformat()  # noqa: DTZ005
    _write_report(report_path.parent, report)
    return {"restored": len(plan), "folder": str(folder)}
