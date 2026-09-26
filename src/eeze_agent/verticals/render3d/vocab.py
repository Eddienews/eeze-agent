"""3D scene vocabulary — what the brain may express, derived from the code.

TEST-LOCKED against the pydantic validators (see `tests/test_specwriter.py`): the object
kinds, step ops and required fields below must match what `Scene3DSpec` actually accepts.
"""

from __future__ import annotations

from typing import Any

OBJECT_KINDS: dict[str, str] = {
    "cube": "box (params: size)",
    "sphere": "sphere (params: radius)",
    "torus": "ring (params: major_radius, minor_radius)",
    "cylinder": "cylinder (params: radius, depth)",
    "cone": "cone (params: radius, depth)",
    "plane": "flat plane (params: size)",
    "text": "extruded 3D text — REQUIRES a `text` string (params: size, extrude)",
}

OBJECT_FIELDS = {
    "kind": "one of the object kinds above",
    "name": "optional object name (string)",
    "text": "the string when kind == 'text'",
    "location": "[x, y, z] world position (default [0,0,0])",
    "rotation": "[rx, ry, rz] degrees XYZ (default [0,0,0])",
    "scale": "[sx, sy, sz] (default [1,1,1])",
    "color": "[r, g, b] 0..1 (default [0.8,0.8,0.8])",
    "metallic": "0..1 (default 0.0)",
    "roughness": "0..1 (default 0.45)",
    "params": "per-kind numbers, see the kinds above",
}

RENDER_FIELDS = {
    "engine": "BLENDER_EEVEE (default; fastest) | BLENDER_WORKBENCH | CYCLES",
    "resolution": "[width, height] EVEN integers (default [480, 480])",
    "fps": "frames per second for the animation (default 12)",
    "frames": "total animation frames (default 24) — duration = frames / fps",
    "samples": "optional render samples",
    "film_transparent": "true = transparent background",
    "background": "[r, g, b] world colour (default near-black)",
}

STEP_OPS: dict[str, dict[str, Any]] = {
    "save_blend": {"required": [], "optional": ["target"], "what": ".blend scene file"},
    "render_still": {"required": [], "optional": ["frame", "target"], "what": "PNG of one frame (frame >= 1)"},
    "render_animation": {"required": [], "optional": ["target"], "what": "h264 MP4 of the whole animation"},
    "export_glb": {"required": [], "optional": ["target"], "what": ".glb model export"},
}

CONSTRAINTS = [
    "scene.objects needs at least one object; scene must have >= 1 light",
    "camera: location/look_at are [x,y,z]; lens > 0; optional orbit {revolutions>0, radius?, height?} makes the camera circle look_at across the animation",
    "resolution must be even; frames >= 1; fps > 0; light energy > 0",
    "step ids must be unique; `target` is a plain file name (no directories)",
    "`output` = the file name or the step id whose artifact is the deliverable (an animation MP4 when a render_animation step exists)",
]


def op_requirements() -> dict[str, list[str]]:
    """op -> required field list (for tests and prompts)."""
    return {op: list(meta["required"]) for op, meta in STEP_OPS.items()}


def describe_3d_vocab() -> str:
    """Compact, prompt-ready description of what a 3D scene spec can express."""
    lines = ["3D SCENE SPEC — YAML object with fields: name, description, scene, render, steps, output"]
    lines.append("SCENE.OBJECTS — list of objects:")
    lines += [f"- kind {k}: {v}" for k, v in OBJECT_KINDS.items()]
    lines.append("object fields:")
    lines += [f"- {k}: {v}" for k, v in OBJECT_FIELDS.items()]
    lines.append("SCENE.CAMERA: location/look_at [x,y,z], lens (default 50), orbit {revolutions, radius, height}")
    lines.append("SCENE.LIGHTS: list of {kind: sun|area|point, location [x,y,z], energy > 0, color [r,g,b], size}")
    lines.append("RENDER:")
    lines += [f"- {k}: {v}" for k, v in RENDER_FIELDS.items()]
    lines.append("STEPS (step.op — required: fields):")
    for op, meta in STEP_OPS.items():
        req = ", ".join(meta["required"]) or "-"
        opt = ", ".join(meta["optional"]) or "-"
        lines.append(f"- {op}: required({req}) optional({opt}) — {meta['what']}")
    lines.append("CONSTRAINTS:")
    lines += [f"- {c}" for c in CONSTRAINTS]
    return "\n".join(lines)
