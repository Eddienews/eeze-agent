"""Video vertical (C1) — real ffmpeg runs, skipped when ffmpeg is not installed.

Every test that touches media executes ffmpeg for real on tiny synthetic clips
(160x120, <1 s, 10 fps) so the suite stays fast while proving the verified chain:
probe facts, trim+scale, concat (silent + non-silent inputs), thumbnail,
still_to_video, and the honest-failure path (a deliberately wrong expectation must
fail the step — nothing may pretend otherwise).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from eeze_agent.verticals.video import load_spec, run_vertical
from eeze_agent.verticals.video.probe import find_tools, probe

try:
    _FF, _FP = find_tools()
except FileNotFoundError:
    _FF = _FP = None

pytestmark = pytest.mark.skipif(_FF is None, reason="ffmpeg/ffprobe not installed")

W, H, FPS = 160, 120, 10


def _mkvideo(path: Path, *, seconds: float = 1.0, audio: bool = False) -> Path:
    args = [
        str(_FF), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration={seconds}",
    ]
    if audio:
        args += [
            "-f", "lavfi", "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a", "aac", "-shortest",
        ]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, capture_output=True, timeout=120)
    return path


def _mkimage(path: Path) -> Path:
    subprocess.run(
        [str(_FF), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c=red:s={W}x{H}", "-frames:v", "1", str(path)],
        check=True, capture_output=True, timeout=120,
    )
    return path


def _spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spec.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _report(tmp_path: Path) -> dict:
    out = tmp_path / "out"
    assert (out / "edit-report.json").exists()
    return json.loads((out / "edit-report.json").read_text(encoding="utf-8"))


# ---------------- probe ----------------


def test_probe_reads_real_facts(tmp_path: Path):
    src = _mkvideo(tmp_path / "a.mp4", seconds=1.0)
    info = probe(_FP, src)
    assert info.kind == "video"
    assert (info.width, info.height) == (W, H)
    assert info.codec_v == "h264"
    assert info.has_audio is False
    assert info.duration_s == pytest.approx(1.0, abs=0.15)
    assert info.fps == pytest.approx(FPS, abs=0.02)
    assert info.size_bytes and info.size_bytes > 0


# ---------------- verified chains ----------------


def test_trim_and_scale_chain_verifies(tmp_path: Path):
    _mkvideo(tmp_path / "src.mp4", seconds=1.0)
    spec = _spec(tmp_path, f"""
name: chain
sources:
  src: {tmp_path / "src.mp4"}
steps:
  - id: cut
    op: trim
    input: src
    start: 0.2
    duration: 0.5
  - id: shaped
    op: scale
    input: cut
    size: [80, 60]
output: chain.mp4
""")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    assert summary["failed"] == 0 and summary["ok"] == 2
    assert summary["output"] and Path(summary["output"]).exists()
    final = probe(_FP, Path(summary["output"]))
    assert (final.width, final.height) == (80, 60)
    assert final.duration_s == pytest.approx(0.5, abs=0.15)
    rep = _report(tmp_path)
    assert [r["status"] for r in rep["steps"]] == ["ok", "ok"]
    assert rep["output_sha256"]


def test_concat_mixes_silent_and_audio_inputs(tmp_path: Path):
    _mkvideo(tmp_path / "silent.mp4", seconds=0.6, audio=False)
    _mkvideo(tmp_path / "loud.mp4", seconds=0.6, audio=True)
    spec = _spec(tmp_path, f"""
name: join
sources:
  a: {tmp_path / "silent.mp4"}
  b: {tmp_path / "loud.mp4"}
steps:
  - id: joined
    op: concat
    inputs: [a, b]
    size: [80, 60]
    fps: 10
output: joined.mp4
""")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    assert summary["failed"] == 0, _report(tmp_path)["steps"]
    final = probe(_FP, Path(summary["output"]))
    assert final.duration_s == pytest.approx(1.2, abs=0.2)
    assert final.has_audio is True
    assert (final.width, final.height) == (80, 60)
    rep = _report(tmp_path)
    assert any("normalized" in n for n in rep["steps"][0]["notes"])


def test_still_to_video_and_thumbnail(tmp_path: Path):
    _mkimage(tmp_path / "logo.png")
    spec = _spec(tmp_path, f"""
name: card
sources:
  logo: {tmp_path / "logo.png"}
steps:
  - id: card
    op: still_to_video
    source: logo
    duration: 0.6
    size: [80, 60]
    fps: 10
  - id: cover
    op: thumbnail
    input: card
    at: 0.2
output: card.png
""")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    assert summary["failed"] == 0, _report(tmp_path)["steps"]
    final = probe(_FP, Path(summary["output"]))
    assert final.kind == "image"
    assert (final.width, final.height) == (80, 60)
    video = probe(_FP, tmp_path / "out" / "work" / "01-card.mp4")
    assert video.duration_s == pytest.approx(0.6, abs=0.15)
    assert video.has_audio is True  # silent track added on purpose


def test_video_filename_selects_video_before_trailing_thumbnail(tmp_path: Path):
    _mkimage(tmp_path / "logo.png")
    spec = _spec(tmp_path, f"""
name: card
sources:
  logo: {tmp_path / "logo.png"}
steps:
  - id: card
    op: still_to_video
    source: logo
    duration: 0.6
    size: [80, 60]
    fps: 10
  - id: cover
    op: thumbnail
    input: card
    at: 0.2
output: card.mp4
""")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    final = Path(summary["output"])
    assert final.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
    assert probe(_FP, final).kind == "video"
    assert _report(tmp_path)["output_facts"]["kind"] == "video"
    assert (tmp_path / "out" / "work" / "02-cover.png").is_file()


def test_video_filename_refuses_when_only_an_image_exists(tmp_path: Path):
    _mkimage(tmp_path / "logo.png")
    spec = _spec(tmp_path, f"""
name: cover
sources:
  logo: {tmp_path / "logo.png"}
steps:
  - id: image
    op: thumbnail
    input: logo
    at: 0
output: cover.mp4
""")
    with pytest.raises(ValueError, match="compatible"):
        run_vertical(spec, out_dir=tmp_path / "out")
    assert not (tmp_path / "out" / "cover.mp4").exists()


# ---------------- honest failure ----------------


def test_wrong_expectation_fails_the_step_and_skips_the_rest(tmp_path: Path):
    _mkvideo(tmp_path / "short.mp4", seconds=0.8)
    spec = _spec(tmp_path, f"""
name: honest
sources:
  src: {tmp_path / "short.mp4"}
steps:
  - id: greedy
    op: trim
    input: src
    start: 0.0
    duration: 5.0
  - id: never
    op: scale
    input: greedy
    size: [80, 60]
output: honest.mp4
""")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    assert summary["failed"] == 1 and summary["skipped"] == 1
    assert summary["output"] is None
    rep = _report(tmp_path)
    problems = rep["steps"][0]["problems"]
    assert any("duration" in p and "of 5.0s" in p for p in problems)
    assert rep["steps"][1]["status"] == "skipped"
    assert rep["output_sha256"] is None


def test_bad_spec_is_refused_before_ffmpeg(tmp_path: Path):
    spec = _spec(tmp_path, """
name: bad
steps:
  - id: broken
    op: concat
    inputs: [only-one]
""")
    with pytest.raises(ValueError):  # pydantic ValidationError with a clear message
        load_spec(spec)


def test_relative_out_dir_still_concats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: the concat list must carry ABSOLUTE paths.

    With a relative ``--out`` the list entries were relative too, and the concat
    demuxer resolved them against the list file's own directory — live failure:
    ``Impossible to open 'artifacts/.../work/artifacts/.../work/…-norm1.mp4'``.
    """
    _mkvideo(tmp_path / "a.mp4", seconds=0.5)
    _mkvideo(tmp_path / "b.mp4", seconds=0.5)
    spec = _spec(tmp_path, f"""
name: relative
sources:
  a: {tmp_path / "a.mp4"}
  b: {tmp_path / "b.mp4"}
steps:
  - id: joined
    op: concat
    inputs: [a, b]
    size: [80, 60]
    fps: 10
output: relative.mp4
""")
    monkeypatch.chdir(tmp_path)
    summary = run_vertical(spec, out_dir=Path("out"))  # RELATIVE on purpose
    assert summary["failed"] == 0, _report(tmp_path)["steps"]
    assert Path(summary["output"]).exists()


def test_fill_mode_covers_the_frame_without_bars():
    from eeze_agent.verticals.video import ops
    from eeze_agent.verticals.video.spec import VideoStep

    assert ops.size_filter((1080, 1920), "fill") == (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1")
    assert "pad=" in ops.size_filter((1080, 1920), "fit")
    assert VideoStep(id="s", op="scale", size=(1080, 1920), fit="fill").fit == "fill"
