"""Video vertical runner: execute an edit spec as a VERIFIED ffmpeg chain.

Every step's output is probed (ffprobe) and compared against expectations declared by
the op — duration within tolerance, exact width/height/fps, stream presence, file
present and non-empty. A mismatch fails the step; later steps are marked ``skipped``
(never silently dropped). Evidence kept: every intermediate under ``work/``, the final
artifact copied to ``<out_dir>/<name>.<ext>``, plus ``edit-report.json``, ``report.md``
and ``summary.json``. Unknown facts stay ``null`` — never a fabricated zero.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from . import ops
from .probe import MediaInfo, find_tools, probe
from .spec import VideoStep, load_spec

DURATION_TOL_S = 0.15
DURATION_TOL_FRAC = 0.05
FPS_TOL = 0.02
STEP_TIMEOUT_S = 600.0


def _duration_tol(expected: float) -> float:
    return max(DURATION_TOL_S, DURATION_TOL_FRAC * expected)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _facts(info: MediaInfo) -> dict:
    return {
        "kind": info.kind,
        "width": info.width,
        "height": info.height,
        "duration_s": info.duration_s,
        "fps": info.fps,
        "codec_v": info.codec_v,
        "codec_a": info.codec_a,
        "has_audio": info.has_audio,
        "nb_frames": info.nb_frames,
        "size_bytes": info.size_bytes,
    }


def _compare(expect: dict, info: MediaInfo) -> list[str]:
    """Problems observed against the op's expectations (empty list = verified)."""
    bad: list[str] = []
    if expect.get("kind") is not None and info.kind != expect["kind"]:
        bad.append(f"kind {info.kind!r} != {expect['kind']!r}")
    if expect.get("duration_s") is not None:
        want = float(expect["duration_s"])
        got = info.duration_s
        if got is None:
            bad.append(f"duration unavailable (want {want}s)")
        elif abs(got - want) > _duration_tol(want):
            bad.append(f"duration {got}s not within ±{_duration_tol(want):.2f}s of {want}s")
    for key in ("width", "height"):
        if expect.get(key) is not None and getattr(info, key) != expect[key]:
            bad.append(f"{key} {getattr(info, key)} != {expect[key]}")
    if expect.get("fps") is not None:
        got = info.fps
        if got is None:
            bad.append("fps unavailable")
        elif abs(got - float(expect["fps"])) > FPS_TOL:
            bad.append(f"fps {got} != {expect['fps']}")
    if expect.get("has_audio") is not None and info.has_audio != expect["has_audio"]:
        bad.append(f"has_audio {info.has_audio} != {expect['has_audio']}")
    if info.size_bytes is None or info.size_bytes <= 0:
        bad.append("output file is missing or empty")
    return bad


def _resolve(
    ref: str | None, *, step: VideoStep, sources: dict[str, Path],
    produced: dict[str, Path], prev: str | None,
) -> Path:
    if ref is None:
        if prev is None:
            raise ValueError(f"step {step.id!r}: no input and no previous step")
        ref = prev
    if ref in produced:
        return produced[ref]
    if ref in sources:
        return sources[ref]
    raise ValueError(f"step {step.id!r}: unknown input {ref!r}")


def _run_step(
    step: VideoStep,
    *,
    ff: Path,
    fp: Path,
    work: Path,
    ix: int,
    sources: dict[str, Path],
    produced: dict[str, Path],
    prev: str | None,
    notes: list[str],
) -> tuple[list[str], dict, Path]:
    """Build (argv, expectations, dst) for one step; concat executes its normalize passes."""

    def resolve(ref: str | None = None) -> Path:
        return _resolve(ref, step=step, sources=sources, produced=produced, prev=prev)

    if step.op == "still_to_video":
        src = sources[step.source]  # spec validation guarantees it exists
        dst = work / f"{ix:02d}-{step.id}.mp4"
        fps = step.fps or ops.DEFAULT_FPS
        argv = ops.op_still_to_video(
            ff, src=src, dst=dst, duration=float(step.duration), size=step.size, fps=fps,
            fit=step.fit,
        )
        expect = {
            "kind": "video", "duration_s": step.duration, "width": step.size[0],
            "height": step.size[1], "fps": fps, "has_audio": True,
        }
        return argv, expect, dst

    if step.op == "trim":
        src = resolve(step.input)
        duration = step.duration if step.duration is not None else (step.end - step.start)
        dst = work / f"{ix:02d}-{step.id}.mp4"
        argv = ops.op_trim(ff, src=src, dst=dst, start=float(step.start), duration=float(duration))
        return argv, {"kind": "video", "duration_s": round(float(duration), 4)}, dst

    if step.op == "scale":
        src = resolve(step.input)
        dst = work / f"{ix:02d}-{step.id}.mp4"
        argv = ops.op_scale(ff, src=src, dst=dst, size=step.size, fit=step.fit)
        return argv, {"kind": "video", "width": step.size[0], "height": step.size[1]}, dst

    if step.op == "fps":
        src = resolve(step.input)
        dst = work / f"{ix:02d}-{step.id}.mp4"
        argv = ops.op_fps(ff, src=src, dst=dst, rate=float(step.fps))
        return argv, {"kind": "video", "fps": step.fps}, dst

    if step.op == "concat":
        paths = [resolve(ref) for ref in (step.inputs or [])]
        size = step.size
        if size is None:
            first = probe(fp, paths[0])
            if first.width is None or first.height is None:
                raise RuntimeError(f"step {step.id!r}: cannot infer size from {paths[0].name}")
            size = (first.width, first.height)
        fps = step.fps or ops.DEFAULT_FPS
        normalized: list[Path] = []
        total = 0.0
        for k, path in enumerate(paths, start=1):
            info = probe(fp, path)
            if info.duration_s is None:
                raise RuntimeError(f"step {step.id!r}: {path.name} has no measurable duration")
            norm = work / f"{ix:02d}-{step.id}-norm{k}.mp4"
            argv_n = ops.op_normalize(
                ff, src=path, dst=norm, size=size, fps=fps, has_audio=info.has_audio,
                duration=float(info.duration_s),
            )
            proc = subprocess.run(
                argv_n, capture_output=True, timeout=STEP_TIMEOUT_S, check=False
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"normalize of {path.name} failed (exit {proc.returncode}): "
                    f"{proc.stderr.decode('utf-8', 'replace').strip()[-200:]}"
                )
            ninfo = probe(fp, norm)
            total += ninfo.duration_s or 0.0
            normalized.append(norm)
            notes.append(f"normalized {path.name} ({ninfo.duration_s}s, audio={ninfo.has_audio})")
        list_file = work / f"{ix:02d}-{step.id}.txt"
        # The concat demuxer resolves relative entries against the LIST FILE's own
        # directory — they must be absolute (an out_dir relative to the CWD broke this
        # live: entries became work/artifacts/.../04-joined-norm1.mp4).
        list_file.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in normalized),
            encoding="utf-8",
        )
        dst = work / f"{ix:02d}-{step.id}.mp4"
        argv = ops.op_concat(ff, list_file=list_file, dst=dst)
        expect = {
            "kind": "video", "duration_s": round(total, 4), "width": size[0],
            "height": size[1], "fps": fps, "has_audio": True,
        }
        return argv, expect, dst

    if step.op == "thumbnail":
        src = resolve(step.input)
        dst = work / f"{ix:02d}-{step.id}.png"
        argv = ops.op_thumbnail(ff, src=src, dst=dst, at=float(step.at))
        sinfo = probe(fp, src)
        return argv, {"kind": "image", "width": sinfo.width, "height": sinfo.height}, dst

    raise ValueError(f"step {step.id!r}: unsupported op {step.op!r}")


def _markdown(report: dict) -> str:
    lines = [f"# Video edit report — {report['name']}", ""]
    if report.get("description"):
        lines += [report["description"], ""]
    lines += [
        f"- spec: `{report['spec']}`",
        f"- ffmpeg: `{report['ffmpeg']}`",
        f"- output: `{report['output']}`",
        f"- sha256: `{report['output_sha256']}`",
        "",
        "## Steps",
        "",
        "| # | step | op | status | ms | expected | observed |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, rec in enumerate(report["steps"], start=1):
        exp = json.dumps(rec["expect"], separators=(",", ":")) if rec.get("expect") else "—"
        act = json.dumps(rec["actual"], separators=(",", ":")) if rec.get("actual") else "—"
        lines.append(
            f"| {i} | {rec['id']} | {rec['op']} | {rec['status']} | {rec['ms']} | {exp} | {act} |"
        )
    problems = [(r["id"], p) for r in report["steps"] for p in r["problems"]]
    lines += ["", "## Problems", ""]
    lines += [f"- {sid}: {p}" for sid, p in problems] if problems else ["- none"]
    notes = [(r["id"], n) for r in report["steps"] for n in r.get("notes") or []]
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {sid}: {n}" for sid, n in notes]
    if report.get("output_facts"):
        lines += ["", "## Output facts", "", "```json",
                  json.dumps(report["output_facts"], indent=2), "```"]
    return "\n".join(lines) + "\n"


def run_vertical(
    spec_path: Path,
    out_dir: Path | None = None,
    ffmpeg_dir: str | Path | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Run the edit spec; returns the summary (also written to ``<out_dir>/summary.json``)."""
    spec_path = Path(spec_path)
    spec = load_spec(spec_path)
    ff, fp = find_tools(ffmpeg_dir)
    repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[4]
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(out_dir) if out_dir else repo_root / "artifacts" / "video" / f"{stamp}-{spec.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)

    sources: dict[str, Path] = {}
    for name, raw in spec.sources.items():
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(f"source {name!r} not found: {path}")
        sources[name] = path

    started = time.time()
    steps_out: list[dict] = []
    produced: dict[str, Path] = {}
    prev: str | None = None
    failed = False
    final_path: Path | None = None
    final_info: MediaInfo | None = None

    for ix, step in enumerate(spec.steps, start=1):
        rec: dict = {
            "id": step.id, "op": step.op, "status": "failed", "ms": None, "output": None,
            "expect": None, "actual": None, "problems": [], "notes": [],
        }
        if failed:
            rec["status"] = "skipped"
            rec["problems"] = ["previous step failed"]
            steps_out.append(rec)
            continue
        t0 = time.perf_counter()
        dst: Path | None = None
        try:
            argv, expect, dst = _run_step(
                step, ff=ff, fp=fp, work=work, ix=ix, sources=sources,
                produced=produced, prev=prev, notes=rec["notes"],
            )
            rec["expect"] = expect
            rec["command"] = " ".join(f'"{a}"' if " " in a else a for a in argv)
            proc = subprocess.run(argv, capture_output=True, timeout=STEP_TIMEOUT_S, check=False)
            if proc.returncode != 0:
                rec["problems"].append(
                    f"ffmpeg exit {proc.returncode}: "
                    f"{proc.stderr.decode('utf-8', 'replace').strip()[-300:]}"
                )
            else:
                info = probe(fp, dst)
                rec["actual"] = _facts(info)
                rec["problems"] = _compare(expect, info)
                if not rec["problems"]:
                    rec["status"] = "ok"
                    produced[step.id] = dst
                    prev = step.id
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            rec["problems"].append(f"{type(exc).__name__}: {exc}")
        rec["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if dst is not None and dst.exists():
            rec["output"] = str(dst.relative_to(out_dir)).replace("\\", "/")
        if rec["status"] != "ok":
            failed = True
        steps_out.append(rec)

    if not failed:
        pick = spec.output if spec.output in produced else spec.steps[-1].id
        if spec.output and spec.output not in produced:
            suffix = Path(spec.output).suffix.lower()
            if suffix not in {".mp4", ".png"}:
                raise ValueError(f"unsupported video output extension: {suffix!r}")
            matches = [step.id for step in spec.steps if step.id in produced
                       and produced[step.id].suffix.lower() == suffix]
            if not matches:
                raise ValueError(f"no compatible output for {spec.output!r}")
            pick = matches[-1]
        source_out = produced[pick]
        ext = source_out.suffix.lower()
        name = spec.output if (spec.output and spec.output not in produced) else f"{spec.name}{ext}"
        final_path = out_dir / name
        shutil.copy2(source_out, final_path)
        final_info = probe(fp, final_path)
        expected_kind = {".mp4": "video", ".png": "image"}.get(final_path.suffix.lower())
        if final_info.kind != expected_kind:
            final_path.unlink()
            raise ValueError(f"output media kind {final_info.kind!r} is not compatible with {name!r}")

    summary = {
        "spec": str(spec_path),
        "name": spec.name,
        "steps": len(spec.steps),
        "ok": sum(1 for r in steps_out if r["status"] == "ok"),
        "failed": sum(1 for r in steps_out if r["status"] == "failed"),
        "skipped": sum(1 for r in steps_out if r["status"] == "skipped"),
        "output": str(final_path) if final_path else None,
        "out_dir": str(out_dir),
        "report": str(out_dir / "report.md"),
        "duration_s": round(time.time() - started, 1),
    }
    report = {
        "spec": str(spec_path),
        "name": spec.name,
        "description": spec.description,
        "ffmpeg": str(ff),
        "ffprobe": str(fp),
        "out_dir": str(out_dir),
        "steps": steps_out,
        "output": str(final_path) if final_path else None,
        "output_facts": _facts(final_info) if final_info else None,
        "output_sha256": _sha256(final_path) if final_path else None,
        "summary": summary,
    }
    (out_dir / "edit-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
