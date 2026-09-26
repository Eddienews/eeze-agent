"""render3d vertical (C2) — payload/script unit tests + one live Blender run (skipped
when Blender is not installed).

The unit half needs no Blender: the payload builder and the generated script are text,
so they are asserted directly. The live half runs ONE tiny scene (64x64, 6 frames,
workbench) through the real binary and checks every artifact, including the GLB magic
bytes and the .blend header.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eeze_agent.verticals.render3d import find_blender, load_spec, run_vertical
from eeze_agent.verticals.render3d.script import EXTENSIONS, SCRIPT, build_payload

try:
    _BLENDER = find_blender()
except FileNotFoundError:
    _BLENDER = None


# ---------------- unit (no Blender needed) ----------------


def _spec(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scene.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """
name: mini
scene:
  objects:
    - kind: cube
steps:
  - id: still
    op: render_still
    frame: 2
"""


def test_payload_carries_scene_and_absolute_step_paths(tmp_path: Path):
    spec = load_spec(_spec(tmp_path, MINIMAL))
    outs = {"still": tmp_path / "work" / "01-still.png"}
    payload = build_payload(spec, outs, out_dir=tmp_path / "work")
    assert payload["name"] == "mini"
    assert payload["scene"]["objects"][0]["kind"] == "cube"
    assert payload["steps"][0]["out"] == outs["still"].resolve().as_posix()
    assert Path(payload["steps"][0]["out"]).is_absolute()


def test_generated_script_guards_and_markers():
    # The two live-found Blender behaviours must stay encoded in the script text.
    assert "use_file_extension = False" in SCRIPT
    assert "EEZE-STEP" in SCRIPT and "EEZE-DONE" in SCRIPT and "EEZE-BUILD-FAIL" in SCRIPT
    for op in EXTENSIONS:
        assert f"def step_{op}" in SCRIPT
    assert set(EXTENSIONS) == {"save_blend", "render_still", "render_animation", "export_glb"}


def test_spec_validation_rejects_bad_input(tmp_path: Path):
    with pytest.raises(ValueError):
        load_spec(_spec(tmp_path, "name: t\nscene:\n  objects:\n    - kind: text\nsteps:\n  - id: a\n    op: render_still\n"))
    with pytest.raises(ValueError):
        load_spec(_spec(tmp_path, MINIMAL + "\nrender:\n  resolution: [101, 64]\n"))
    with pytest.raises(ValueError):
        load_spec(_spec(tmp_path, "name: t\nscene:\n  objects:\n    - kind: cube\nsteps: []\n"))
    with pytest.raises(ValueError):
        load_spec(_spec(tmp_path, "name: t\nscene:\n  objects: []\nsteps:\n  - id: a\n    op: export_glb\n"))


# ---------------- live (needs Blender) ----------------


@pytest.mark.skipif(_BLENDER is None, reason="Blender not installed")
def test_live_scene_renders_and_verifies(tmp_path: Path):
    spec = _spec(
        tmp_path,
        """
name: live-mini
description: one tiny scene, all four ops, verified
scene:
  objects:
    - kind: cube
      name: box
      params: {size: 2.0}
    - kind: text
      text: "e"
      location: [0, -2.2, 0]
      rotation: [90, 0, 0]
      params: {size: 1.4, extrude: 0.08}
  camera:
    location: [4.5, -4.5, 3.0]
    look_at: [0, 0, 0]
    orbit: {revolutions: 1.0}
  lights:
    - kind: sun
      energy: 4.0
render:
  engine: BLENDER_WORKBENCH
  resolution: [64, 64]
  fps: 6
  frames: 6
steps:
  - id: still
    op: render_still
    frame: 3
  - id: anim
    op: render_animation
  - id: scene
    op: save_blend
  - id: model
    op: export_glb
output: anim
""",
    )
    out = tmp_path / "out"
    summary = run_vertical(spec, out_dir=out, blender_path=_BLENDER, timeout_s=300)
    report = json.loads((out / "render-report.json").read_text(encoding="utf-8"))
    assert summary["failed"] == 0, report["steps"]
    assert summary["ok"] == 4
    assert summary["blender"].startswith("Blender ")
    assert Path(summary["output"]).exists()
    assert (out / "work" / "run_blender.py").exists()  # generated script kept as evidence
    assert (out / "work" / "blender.log").exists()
    glb = out / "work" / "04-model.glb"
    assert glb.read_bytes()[:4] == b"glTF"
    blend = out / "work" / "03-scene.blend"
    assert blend.stat().st_size > 1000
    anim = out / "work" / "02-anim.mp4"
    assert anim.stat().st_size > 1000


@pytest.mark.skipif(_BLENDER is None, reason="Blender not installed")
def test_live_unknown_op_fails_honestly(tmp_path: Path):
    """An engine Blender does not expose must fail the build, not fake success."""
    spec = _spec(
        tmp_path,
        """
name: bad-engine
scene:
  objects:
    - kind: cube
render:
  engine: BLENDER_WORKBENCH
  resolution: [64, 64]
  frames: 2
steps:
  - id: anim
    op: render_animation
""",
    )
    # Force an engine the binary rejects by editing the payload after validation.
    out = tmp_path / "out"
    out.mkdir()
    (out / "work").mkdir()
    import eeze_agent.verticals.render3d.runner as runner_mod

    real_build = runner_mod.build_payload

    def broken_build(spec_, steps_out, *, out_dir):
        data = real_build(spec_, steps_out, out_dir=out_dir)
        data["render"]["engine"] = "NOT_AN_ENGINE"
        return data

    runner_mod.build_payload = broken_build
    try:
        summary = run_vertical(spec, out_dir=out, blender_path=_BLENDER, timeout_s=300)
    finally:
        runner_mod.build_payload = real_build
    assert summary["failed"] == 1
    assert summary["output"] is None
