"""A18: local photo edits use real ffmpeg and verify the advertised final image."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from eeze_agent.verticals.video.probe import find_tools, probe

try:
    _FF, _FP = find_tools()
except FileNotFoundError:
    _FF = _FP = None

pytestmark = pytest.mark.skipif(_FF is None, reason="ffmpeg/ffprobe not installed")


def _image(path: Path) -> Path:
    subprocess.run(
        [str(_FF), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=160x120:rate=1", "-frames:v", "1", str(path)],
        check=True, capture_output=True, timeout=30,
    )
    return path


def _cli(spec: Path, out: Path) -> subprocess.CompletedProcess[str]:
    # Keep cli.py's .env loading in a child so it cannot contaminate other tests.
    return subprocess.run(
        [sys.executable, "-m", "eeze_agent.cli", "photo", str(spec), "--out", str(out)],
        capture_output=True, text=True, timeout=60, check=False,
    )


def test_crop_resize_adjust_produces_verified_png_and_preserves_source(tmp_path: Path):
    from eeze_agent.verticals.photo import run_vertical

    source = _image(tmp_path / "source.png")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = tmp_path / "edit.yaml"
    spec.write_text(f"""
name: portrait
source: {source.as_posix()}
steps:
  - id: focus
    op: crop
    x: 20
    y: 10
    width: 100
    height: 80
  - id: size
    op: resize
    width: 200
    height: 160
  - id: finish
    op: adjust
    brightness: 0.2
    contrast: 1.1
    saturation: 1.2
output: edited.png
""", encoding="utf-8")
    out = tmp_path / "out"
    summary = run_vertical(spec, out_dir=out)
    final = out / "edited.png"
    assert summary["ok"] == 3 and summary["failed"] == 0
    assert Path(summary["output"]) == final
    assert final.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    measured = probe(_FP, final)
    assert measured.kind == "image" and (measured.width, measured.height) == (200, 160)
    report = json.loads((out / "edit-report.json").read_text(encoding="utf-8"))
    assert report["output_facts"]["kind"] == "image"
    assert [step["status"] for step in report["steps"]] == ["ok", "ok", "ok"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    baseline = subprocess.run(
        [str(_FF), "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-vf", "crop=100:80:20:10,scale=200:160", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True, timeout=30,
    ).stdout
    edited_pixels = subprocess.run(
        [str(_FF), "-hide_banner", "-loglevel", "error", "-i", str(final),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True, timeout=30,
    ).stdout
    assert len(edited_pixels) == len(baseline) and edited_pixels != baseline


def test_photo_edit_refuses_out_of_bounds_crop_without_final(tmp_path: Path):
    from eeze_agent.verticals.photo import run_vertical

    source = _image(tmp_path / "source.png")
    spec = tmp_path / "bad.yaml"
    spec.write_text(f"""
name: badcrop
source: {source.as_posix()}
steps:
  - id: outside
    op: crop
    x: 150
    y: 0
    width: 30
    height: 80
  - id: never
    op: resize
    width: 64
    height: 64
output: bad.png
""", encoding="utf-8")
    summary = run_vertical(spec, out_dir=tmp_path / "out")
    assert summary["failed"] == 1 and summary["skipped"] == 1
    assert summary["output"] is None and not (tmp_path / "out" / "bad.png").exists()
    report = json.loads((tmp_path / "out" / "edit-report.json").read_text(encoding="utf-8"))
    assert "outside the source" in report["steps"][0]["problem"]


def test_photo_edit_never_replaces_final_created_during_run(tmp_path: Path, monkeypatch):
    from eeze_agent.verticals.photo import runner

    source = _image(tmp_path / "source.png")
    spec = tmp_path / "edit.yaml"
    spec.write_text(f"""
name: race
source: {source.as_posix()}
steps:
  - id: resize
    op: resize
    width: 80
    height: 60
output: edited.png
""", encoding="utf-8")
    final = tmp_path / "out" / "edited.png"
    original_filter = runner._filter

    def file_arrives(step, info):
        final.write_bytes(b"foreign-file")
        return original_filter(step, info)

    monkeypatch.setattr(runner, "_filter", file_arrives)
    with pytest.raises(ValueError, match="already exists"):
        runner.run_vertical(spec, out_dir=final.parent)
    assert final.read_bytes() == b"foreign-file"


def test_photo_cli_runs_a_real_edit(tmp_path: Path):
    source = _image(tmp_path / "source.png")
    spec = tmp_path / "edit.yaml"
    spec.write_text(f"""
name: command
source: {source.as_posix()}
steps:
  - id: smaller
    op: resize
    width: 80
    height: 60
output: command.png
""", encoding="utf-8")
    out = tmp_path / "out"
    result = _cli(spec, out)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["ok"] == 1 and Path(output["output"]).is_file()


def test_photo_spec_refuses_unsafe_or_nonfinite_values(tmp_path: Path):
    from eeze_agent.verticals.photo import load_spec

    base = "name: safe\nsource: input.png\nsteps: [{id: finish, op: adjust}]\n"
    for output in ("../escape.png", "C:/tmp/escape.png", "other.jpg"):
        path = tmp_path / "unsafe.yaml"
        path.write_text(base + f"output: {output}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="output"):
            load_spec(path)
    path = tmp_path / "nonfinite.yaml"
    path.write_text(base.replace("op: adjust", "op: adjust, brightness: .nan")
                    + "output: safe.png\n", encoding="utf-8")
    with pytest.raises(ValueError, match="brightness"):
        load_spec(path)
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(TypeError, match="YAML mapping"):
        load_spec(path)


def test_photo_refuses_disguised_video_as_png_source(tmp_path: Path):
    from eeze_agent.verticals.photo import run_vertical

    source = tmp_path / "fake.png"
    subprocess.run(
        [str(_FF), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=80x60:duration=0.5", "-f", "mp4", str(source)],
        check=True, capture_output=True, timeout=30,
    )
    spec = tmp_path / "edit.yaml"
    spec.write_text(f"""
name: fake
source: {source.as_posix()}
steps:
  - id: size
    op: resize
    width: 40
    height: 30
output: edited.png
""", encoding="utf-8")
    with pytest.raises(ValueError, match="genuine PNG or JPEG"):
        run_vertical(spec, out_dir=tmp_path / "out")
    assert not (tmp_path / "out" / "edited.png").exists()


def test_photo_accepts_real_jpeg(tmp_path: Path):
    jpeg = tmp_path / "source.jpg"
    subprocess.run(
        [str(_FF), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=size=160x120:rate=1", "-frames:v", "1", str(jpeg)],
        check=True, capture_output=True, timeout=30,
    )
    before = hashlib.sha256(jpeg.read_bytes()).hexdigest()
    spec = tmp_path / "jpeg.yaml"
    spec.write_text(f"""
name: jpeg-edit
source: {jpeg.as_posix()}
steps:
  - id: crop
    op: crop
    x: 10
    y: 10
    width: 100
    height: 80
output: from-jpeg.png
""", encoding="utf-8")
    out = tmp_path / "out"
    result = _cli(spec, out)
    assert result.returncode == 0, result.stderr
    assert probe(_FP, out / "from-jpeg.png").kind == "image"
    assert hashlib.sha256(jpeg.read_bytes()).hexdigest() == before


def test_photo_cli_returns_nonzero_for_failed_crop(tmp_path: Path):
    source = _image(tmp_path / "source.png")
    spec = tmp_path / "bad.yaml"
    spec.write_text(f"""
name: badcrop
source: {source.as_posix()}
steps:
  - id: outside
    op: crop
    x: 150
    y: 0
    width: 30
    height: 80
output: bad.png
""", encoding="utf-8")
    out = tmp_path / "out"
    process = _cli(spec, out)
    assert process.returncode == 1
    result = json.loads(process.stdout)
    assert result["failed"] == 1 and result["output"] is None
    assert not (out / "bad.png").exists()


def test_twilight_feathers_upper_frame_without_changing_lower_pixels(tmp_path: Path):
    from eeze_agent.verticals.photo import run_vertical

    source = tmp_path / "source.png"
    subprocess.run(
        [str(_FF), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x808080:s=96x96", "-frames:v", "1", str(source)],
        check=True, capture_output=True, timeout=30,
    )
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    spec = tmp_path / "twilight.yaml"
    spec.write_text(f"""
name: upper-dusk
source: {source.as_posix()}
steps:
  - id: evening
    op: twilight
    strength: 0.75
    fade_start: 0.2
    fade_end: 0.7
output: evening.png
""", encoding="utf-8")
    out = tmp_path / "out"
    summary = run_vertical(spec, out_dir=out)
    final = out / "evening.png"
    assert summary["ok"] == 1 and final.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_sha
    assert probe(_FP, final).width == 96
    report = json.loads((out / "edit-report.json").read_text())
    assert report["output_sha256"] == hashlib.sha256(final.read_bytes()).hexdigest()

    def rgb_rows(image: Path) -> bytes:
        return subprocess.run(
            [str(_FF), "-v", "error", "-i", str(image), "-f", "rawvideo",
             "-pix_fmt", "rgb24", "pipe:1"], check=True, capture_output=True, timeout=30,
        ).stdout

    before, after = rgb_rows(source), rgb_rows(final)
    def pixel(data: bytes, y: int) -> tuple[int, int, int]:
        i = (y * 96 + 48) * 3
        return tuple(data[i:i + 3])

    upper_delta = sum(abs(a - b) for a, b in zip(pixel(before, 5), pixel(after, 5)))
    middle_delta = sum(abs(a - b) for a, b in zip(pixel(before, 45), pixel(after, 45)))
    bottom_delta = sum(abs(a - b) for a, b in zip(pixel(before, 90), pixel(after, 90)))
    assert upper_delta > middle_delta > bottom_delta
    assert bottom_delta <= 3  # round-trip codec noise only
    assert pixel(after, 5)[2] > pixel(after, 5)[0]  # cool blue tint


@pytest.mark.parametrize("field,value", [
    ("strength", -0.1), ("strength", 1.1), ("strength", ".nan"),
    ("fade_start", -0.1), ("fade_end", 1.1),
    ("fade_start", 0.8),
])
def test_twilight_refuses_unsafe_parameters(tmp_path: Path, field: str, value: float | str):
    from eeze_agent.verticals.photo import load_spec

    params = {"strength": 0.75, "fade_start": 0.2, "fade_end": 0.7}
    params[field] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(
        "name: fail\nsource: input.png\nsteps:\n  - id: dusk\n    op: twilight\n"
        + "".join(f"    {key}: {item}\n" for key, item in params.items())
        + "output: fail.png\n", encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_spec(path)


def test_twilight_rejects_geometry_and_adjustment_fields():
    from pydantic import ValidationError

    from eeze_agent.verticals.photo.spec import PhotoStep

    base = {"id": "dusk", "op": "twilight", "strength": 0.7,
            "fade_start": 0.2, "fade_end": 0.7}
    for field, value in (("width", 64), ("brightness", -0.1), ("x", 0)):
        with pytest.raises(ValidationError):
            PhotoStep.model_validate({**base, field: value})

