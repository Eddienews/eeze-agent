"""Video vertical (C1): spec-driven ffmpeg editing, every step ffprobe-verified.

The spec is the contract between a brain (which writes it — C2 knowledge pack) and the
tools (which execute it deterministically): a fixed op set, fixed encode settings, and
each step's output measured against the op's expectations before the chain proceeds.
"""

from __future__ import annotations

from .runner import run_vertical
from .spec import VideoSpec, load_spec

__all__ = ["VideoSpec", "load_spec", "run_vertical"]
