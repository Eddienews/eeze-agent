"""3D vertical (C2): declarative scenes rendered in Blender headless, artifacts verified.

The spec describes the scene (primitives, transforms, materials, camera, lights) and the
render settings; the runner generates ONE Blender script, executes it headless, and
verifies every declared artifact for real (file facts, magic bytes, ffprobe) — a step
whose artifact does not match is reported FAILED, never a silent pass.
"""

from .blender import find_blender
from .runner import run_vertical
from .spec import Scene3DSpec, load_spec

__all__ = ["Scene3DSpec", "find_blender", "load_spec", "run_vertical"]
