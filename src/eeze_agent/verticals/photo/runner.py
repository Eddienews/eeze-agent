"""Execute bounded photo edits locally; verify every intermediate and final PNG."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from eeze_agent.verticals.video.probe import MediaInfo, find_tools, probe

from .spec import PhotoStep, load_spec

STEP_TIMEOUT_S = 120.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _facts(info: MediaInfo) -> dict:
    return {
        "kind": info.kind,
        "width": info.width,
        "height": info.height,
        "codec_v": info.codec_v,
        "size_bytes": info.size_bytes,
    }


def _filter(step: PhotoStep, info: MediaInfo) -> tuple[str, tuple[int, int]]:
    if step.op == "crop":
        assert step.x is not None and step.y is not None
        assert step.width is not None and step.height is not None
        if (info.width is None or info.height is None
                or step.x + step.width > info.width or step.y + step.height > info.height):
            raise ValueError("crop rectangle is outside the source image")
        return f"crop={step.width}:{step.height}:{step.x}:{step.y}", (step.width, step.height)
    if step.op == "resize":
        assert step.width is not None and step.height is not None
        return f"scale={step.width}:{step.height}:flags=lanczos", (step.width, step.height)
    assert info.width is not None and info.height is not None
    if step.op == "twilight":
        assert step.strength is not None and step.fade_start is not None and step.fade_end is not None
        start = step.fade_start * info.height
        end = step.fade_end * info.height
        # A bounded vertical mask, not semantic sky segmentation. Lower pixels stay unchanged.
        opacity = f"({step.strength}*min(1\\,max(0\\,({end}-Y)/({end-start}))))"
        channels = [
            f"{channel}='({name}(X\\,Y))*(1-{opacity})+{target}*{opacity}'"
            for channel, name, target in (("r", "r", 16), ("g", "g", 27), ("b", "b", 67))
        ]
        return "format=rgb24,geq=" + ":".join(channels), (info.width, info.height)
    return (f"eq=brightness={step.brightness}:contrast={step.contrast}:"
            f"saturation={step.saturation}"), (info.width, info.height)


def run_vertical(
    spec_path: Path, out_dir: Path | None = None, ffmpeg_dir: str | Path | None = None,
    repo_root: Path | None = None,
) -> dict:
    spec = load_spec(Path(spec_path))
    ff, fp = find_tools(ffmpeg_dir)
    source = Path(spec.source)
    if not source.is_absolute():
        source = Path(spec_path).resolve().parent / source
    if not source.is_file():
        raise FileNotFoundError(f"source image not found: {source}")
    source_info = probe(fp, source)
    allowed = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg"}
    if source_info.kind != "image" or source_info.codec_v != allowed.get(source.suffix.lower()):
        raise ValueError("source must be a genuine PNG or JPEG image")

    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[4]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = Path(out_dir) if out_dir else root / "artifacts" / "photo" / f"{stamp}-{spec.name}"
    final = out / spec.output
    work = out / "work"
    if final.exists() or (work.exists() and any(work.iterdir())):
        raise ValueError("output directory already contains photo edit artifacts")
    work.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    current, current_info = source, source_info
    rows: list[dict] = []
    failed = False
    for index, step in enumerate(spec.steps, start=1):
        row: dict = {"id": step.id, "op": step.op, "status": "skipped" if failed else "failed",
                     "expected": None, "actual": None, "problem": None, "ms": None}
        if failed:
            rows.append(row)
            continue
        t0 = time.perf_counter()
        target = work / f"{index:02d}-{step.id}.png"
        try:
            filter_graph, size = _filter(step, current_info)
            row["expected"] = {"kind": "image", "width": size[0], "height": size[1]}
            command = [str(ff), "-n", "-hide_banner", "-loglevel", "error", "-i", str(current),
                       "-vf", filter_graph, "-frames:v", "1", str(target)]
            result = subprocess.run(command, capture_output=True, timeout=STEP_TIMEOUT_S, check=False)
            if result.returncode:
                raise RuntimeError(f"ffmpeg exit {result.returncode}: "
                                   f"{result.stderr.decode('utf-8', 'replace')[-300:]}")
            actual = probe(fp, target)
            row["actual"] = _facts(actual)
            if (actual.kind != "image" or actual.codec_v != "png"
                    or (actual.width, actual.height) != size
                    or not actual.size_bytes or not target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")):
                raise ValueError("photo step output failed format or dimensions verification")
            row["status"] = "ok"
            current, current_info = target, actual
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            row["problem"] = f"{type(exc).__name__}: {exc}"
            failed = True
        row["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rows.append(row)

    final_info = None
    if not failed:
        # Exclusive creation closes the race between preflight and writing the final.
        try:
            with final.open("xb") as output, current.open("rb") as image:
                shutil.copyfileobj(image, output)
        except FileExistsError as exc:
            raise ValueError("final output already exists") from exc
        final_info = probe(fp, final)
        if (final_info.kind != "image" or final_info.codec_v != "png"
                or not final.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
                or (final_info.width, final_info.height) != (current_info.width, current_info.height)):
            final.unlink(missing_ok=True)
            raise ValueError("final PNG failed independent verification")
    summary = {
        "name": spec.name, "steps": len(rows),
        "ok": sum(row["status"] == "ok" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "skipped": sum(row["status"] == "skipped" for row in rows),
        "output": str(final) if final_info else None,
        "report": str(out / "edit-report.json"),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    report = {"summary": summary, "source_facts": _facts(source_info), "steps": rows,
              "output_facts": _facts(final_info) if final_info else None,
              "output_sha256": _sha256(final) if final_info else None}
    (out / "edit-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
