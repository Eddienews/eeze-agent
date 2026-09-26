"""3D vertical runner: build a declarative scene in Blender headless, VERIFY every artifact.

One Blender invocation per run (a cold headless EEVEE start measured ~36 s on this machine),
so the generated script — ``work/run_blender.py`` + ``work/scene.json``, both kept as
evidence — builds the scene once and executes every step, printing machine-readable status
lines and continuing after a failure. The runner then verifies each declared artifact for
real: file existence/size, GLB magic bytes, .blend header (plain or zstd), PNG facts and
MP4 duration/fps/size via ffprobe when it is installed. A step whose artifact does not
match is reported FAILED, never a silent pass.

Difference from the video vertical (single process per run): steps are independent outputs
of one scene, so there is no `skipped` cascade — every step is judged on its own artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from ..video.probe import MediaInfo, find_tools, probe
from .blender import find_blender
from .script import EXTENSIONS, SCRIPT, build_payload
from .spec import Scene3DSpec, Step3D, load_spec

STEP_LINE = re.compile(r"^EEZE-STEP (\S+) (OK|FAIL) (\S+)s ?(.*)$")
BUILD_FAIL = re.compile(r"^EEZE-BUILD-FAIL (.*)$")
RUN_TIMEOUT_S = 900.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _facts(info: MediaInfo) -> dict:
    return {
        "kind": info.kind,
        "width": info.width,
        "height": info.height,
        "duration_s": info.duration_s,
        "fps": info.fps,
        "codec_v": info.codec_v,
        "has_audio": info.has_audio,
        "size_bytes": info.size_bytes,
    }


def _verify(
    step: Step3D, target: Path, spec: Scene3DSpec, fp: Path | None
) -> tuple[list[str], dict]:
    """Check the step's artifact for real; returns (problems, measured facts)."""
    problems: list[str] = []
    facts: dict = {}
    if not target.exists():
        return [f"artifact missing: {target.name}"], facts
    size = target.stat().st_size
    facts["size_bytes"] = size
    if size <= 0:
        problems.append("artifact is empty")
    width, height = spec.render.resolution

    if step.op == "export_glb":
        with target.open("rb") as fh:
            magic = fh.read(4)
        facts["magic"] = magic.decode("ascii", "replace")
        if magic != b"glTF":
            problems.append(f"GLB magic {magic!r} != b'glTF'")
        if size < 100:
            problems.append(f"glb suspiciously small ({size} B)")
        return problems, facts

    if step.op == "save_blend":
        with target.open("rb") as fh:
            head = fh.read(8)
        zstd = head.startswith(b"\x28\xb5\x2f\xfd")
        facts["magic"] = "zstd" if zstd else head.decode("ascii", "replace").strip("\x00")
        if not zstd and not head.startswith(b"BLENDER"):
            problems.append(f"not a Blender file (header {head!r})")
        if size < 1000:
            problems.append(f"blend suspiciously small ({size} B)")
        return problems, facts

    if fp is None:
        facts["probe"] = "unavailable (ffprobe not found) — size/magic only"
        if size < 1000:
            problems.append(f"file suspiciously small ({size} B)")
        return problems, facts

    info = probe(fp, target)
    facts.update(_facts(info))
    if (info.width, info.height) != (width, height):
        problems.append(f"size {info.width}x{info.height} != {width}x{height}")
    if step.op == "render_still":
        if info.kind != "image":
            problems.append(f"kind {info.kind!r} != 'image'")
    elif step.op == "render_animation":
        if info.kind != "video":
            problems.append(f"kind {info.kind!r} != 'video'")
        want = spec.render.frames / spec.render.fps
        got = info.duration_s
        if got is None:
            problems.append("duration unavailable")
        elif abs(got - want) > max(0.2, 0.06 * want):
            problems.append(f"duration {got}s not within max(0.2s, 6%) of {want:.3f}s")
        if info.fps is not None and abs(info.fps - spec.render.fps) > 0.05:
            problems.append(f"fps {info.fps} != {spec.render.fps}")
    return problems, facts


def run_vertical(
    spec_path: Path | str,
    *,
    out_dir: Path | str | None = None,
    blender_path: str | Path | None = None,
    timeout_s: float | None = None,
    repo_root: Path | None = None,
) -> dict:
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    blender = find_blender(blender_path)
    try:
        _ff, fp = find_tools()
    except FileNotFoundError:
        fp = None
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[4]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out_dir) if out_dir else repo_root / "artifacts" / "3d" / f"{stamp}-{spec.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)

    steps_out: dict[str, Path] = {}
    for ix, step in enumerate(spec.steps, start=1):
        steps_out[step.id] = work / f"{ix:02d}-{step.id}{EXTENSIONS[step.op]}"
    payload = build_payload(spec, steps_out, out_dir=work)
    scene_json = work / "scene.json"
    scene_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    script_path = work / "run_blender.py"
    script_path.write_text(SCRIPT, encoding="utf-8")

    argv = [
        str(blender), "-b", "--factory-startup", "-noaudio",
        "--python", str(script_path), "--", str(scene_json),
    ]
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            argv, capture_output=True, timeout=timeout_s or RUN_TIMEOUT_S, check=False
        )
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
        returncode = None
    blender_log = f"$ {' '.join(argv)}\n\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    (work / "blender.log").write_text(blender_log, encoding="utf-8")

    statuses: dict[str, tuple[str, float, str]] = {}
    build_failure: str | None = None
    for line in stdout.splitlines():
        match = STEP_LINE.match(line.strip())
        if match:
            statuses[match.group(1)] = (match.group(2), float(match.group(3)), match.group(4))
        fail = BUILD_FAIL.match(line.strip())
        if fail:
            build_failure = fail.group(1)
    banner = next(
        (ln.strip() for ln in stdout.splitlines() if ln.strip().startswith("Blender ")),
        "unknown",
    )

    steps_report: list[dict] = []
    for step in spec.steps:
        rec: dict = {
            "id": step.id, "op": step.op, "status": "failed", "ms": None, "output": None,
            "blender_status": None, "detail": None, "facts": {}, "problems": [],
        }
        target = steps_out[step.id]
        status = statuses.get(step.id)
        if status is None:
            rec["problems"].append("no status line from Blender (script stopped before this step)")
            if build_failure:
                rec["problems"].append(f"scene build failed: {build_failure}")
        else:
            verdict, seconds, detail = status
            rec["blender_status"] = verdict
            rec["detail"] = detail
            rec["ms"] = round(seconds * 1000, 1)
            if verdict == "FAIL":
                rec["problems"].append(f"Blender step failed: {detail}")
        if status is None or status[0] == "OK":
            problems, facts = _verify(step, target, spec, fp)
            rec["facts"] = facts
            rec["problems"] += problems
        if rec["blender_status"] == "OK" and not rec["problems"]:
            rec["status"] = "ok"
        if target.exists():
            rec["output"] = target.relative_to(out_dir).as_posix()
        steps_report.append(rec)

    failed = sum(1 for r in steps_report if r["status"] == "failed")
    ok = sum(1 for r in steps_report if r["status"] == "ok")

    final_path: Path | None = None
    final_facts: dict | None = None
    if failed == 0 and not timed_out:
        pick = spec.steps[-1].id
        if spec.output and spec.output in steps_out:
            pick = spec.output
        source = steps_out[pick]
        ext = source.suffix
        name = spec.output if (spec.output and spec.output not in steps_out) else f"{spec.name}{ext}"
        final_path = out_dir / name
        shutil.copy2(source, final_path)
        if fp is not None and ext in (".mp4", ".png"):
            final_facts = _facts(probe(fp, final_path))
        else:
            final_facts = {"size_bytes": final_path.stat().st_size}

    summary = {
        "spec": str(spec_path),
        "name": spec.name,
        "blender": banner,
        "engine": spec.render.engine,
        "steps": len(spec.steps),
        "ok": ok,
        "failed": failed,
        "skipped": 0,  # single Blender process: every step ran, none is skipped-cascaded
        "output": str(final_path) if final_path else None,
        "out_dir": str(out_dir),
        "report": str(out_dir / "report.md"),
        "duration_s": round(time.time() - started, 1),
    }
    report = {
        "spec": str(spec_path),
        "name": spec.name,
        "description": spec.description,
        "blender": banner,
        "blender_path": str(blender),
        "engine": spec.render.engine,
        "resolution": list(spec.render.resolution),
        "fps": spec.render.fps,
        "frames": spec.render.frames,
        "render_returncode": returncode,
        "timed_out": timed_out,
        "steps": steps_report,
        "output": str(final_path) if final_path else None,
        "output_facts": final_facts,
        "output_sha256": _sha256(final_path) if final_path else None,
        "summary": summary,
        "blender_log": str(work / "blender.log"),
        "scene_json": str(scene_json),
        "script": str(script_path),
    }
    (out_dir / "render-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _markdown(report: dict) -> str:
    lines = [f"# 3D render report — {report['name']}", ""]
    if report.get("description"):
        lines += [report["description"], ""]
    engine_line = (
        f"- engine: `{report['engine']}` · {report['resolution'][0]}x{report['resolution'][1]}"
        f" · {report['fps']} fps · {report['frames']} frames"
    )
    lines += [
        f"- spec: `{report['spec']}`",
        f"- blender: `{report['blender']}` — `{report['blender_path']}`",
        engine_line,
        f"- output: `{report['output']}`",
        f"- sha256: `{report['output_sha256']}`",
        f"- blender log: `{report['blender_log']}`",
        "",
        "## Steps",
        "",
        "| # | step | op | status | blender | s | observed |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, rec in enumerate(report["steps"], start=1):
        secs = f"{rec['ms'] / 1000:.2f}" if rec["ms"] is not None else "—"
        facts = json.dumps(rec.get("facts") or {}, separators=(",", ":")) or "—"
        lines.append(
            f"| {i} | {rec['id']} | {rec['op']} | {rec['status']} |"
            f" {rec.get('blender_status') or '—'} | {secs} | {facts} |"
        )
    problems = [(r["id"], p) for r in report["steps"] for p in r["problems"]]
    lines += ["", "## Problems", ""]
    lines += [f"- {sid}: {p}" for sid, p in problems] if problems else ["- none"]
    if report.get("output_facts"):
        lines += ["", "## Output facts", "", "```json", json.dumps(report["output_facts"], indent=2), "```"]
    return "\n".join(lines) + "\n"
