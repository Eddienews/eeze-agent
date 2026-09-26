"""Offline visual proposal validation — never calls a driver or external model."""
from __future__ import annotations

import base64
import struct
import zlib

import pytest

from eeze_agent.core.models import Observation
from eeze_agent.core.visual_fallback import Rect, TargetProposal, review_target


def _png(width: int = 200, height: int = 120, color: int = 0) -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + bytes([color]) * (3 * width) for _ in range(height))
    raw = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return base64.b64encode(raw).decode("ascii")


def _obs(*, pid: int = 11, window_id: int = 22, snapshot_id: str | None = "s1",
         image: str | None = None, degraded: bool = False) -> Observation:
    return Observation(pid=pid, window_id=window_id, snapshot_id=snapshot_id,
                       screenshot_png_b64=_png() if image is None else image, degraded=degraded)


def _target(**changes) -> TargetProposal:
    data = {"pid": 11, "window_id": 22, "snapshot_id": "s1", "image_width": 200,
            "image_height": 120, "box": Rect(20, 20, 40, 20), "x": 35, "y": 30,
            "confidence": 0.98, "evidence": "single save button", "alternatives": 0}
    return TargetProposal(**(data | changes))


def test_visual_target_is_only_image_local_proposal():
    frame = _obs()
    decision = review_target(frame, _target(), _obs(snapshot_id="s2"), Rect(0, 0, 200, 120),
                             captured_at=10.0, now=11.0)
    assert decision.point == (35, 30) and decision.reason == "ok"
    assert decision.coordinate_space == "image-local"  # not directly usable as CUA x/y


@pytest.mark.parametrize(("frame", "proposal", "latest", "region", "age", "reason"), [
    (_obs(image=""), _target(), _obs(), Rect(0, 0, 200, 120), 1.0, "invalid_image"),
    (_obs(image="broken"), _target(), _obs(), Rect(0, 0, 200, 120), 1.0, "invalid_image"),
    (_obs(image=base64.b64encode(base64.b64decode(_png())[:33]).decode()),
     _target(), _obs(), Rect(0, 0, 200, 120), 1.0, "invalid_image"),
    (_obs(snapshot_id=None), _target(), _obs(), Rect(0, 0, 200, 120), 1.0, "identity_mismatch"),
    (_obs(degraded=True), _target(), _obs(), Rect(0, 0, 200, 120), 1.0, "degraded_capture"),
    (_obs(), _target(), _obs(pid=99), Rect(0, 0, 200, 120), 1.0, "identity_mismatch"),
    (_obs(), _target(snapshot_id="older"), _obs(), Rect(0, 0, 200, 120), 1.0, "identity_mismatch"),
    (_obs(), _target(image_width=400), _obs(), Rect(0, 0, 200, 120), 1.0, "geometry_mismatch"),
    (_obs(), _target(box=Rect(195, 20, 20, 20)), _obs(), Rect(0, 0, 200, 120), 1.0, "outside_region"),
    (_obs(), _target(x=10), _obs(), Rect(0, 0, 200, 120), 1.0, "point_outside_box"),
    (_obs(), _target(confidence=0.5), _obs(), Rect(0, 0, 200, 120), 1.0, "ambiguous"),
    (_obs(), _target(alternatives=1), _obs(), Rect(0, 0, 200, 120), 1.0, "ambiguous"),
    (_obs(), _target(), _obs(), Rect(0, 0, 200, 120), 9.0, "stale_capture"),
    (_obs(), _target(), _obs(image=_png(201, 120)), Rect(0, 0, 200, 120), 1.0, "geometry_mismatch"),
    (_obs(), _target(), _obs(image=_png(color=1)), Rect(0, 0, 200, 120), 1.0, "capture_changed"),
])
def test_visual_target_abstains(frame, proposal, latest, region, age, reason):
    decision = review_target(frame, proposal, latest, region, captured_at=10.0, now=10.0 + age)
    assert decision.point is None and decision.reason == reason


def test_visual_target_refuses_no_proposal_and_outside_allowed_region():
    frame = _obs()
    assert review_target(frame, None, _obs(), Rect(0, 0, 200, 120),
                         captured_at=10, now=11).reason == "no_target"
    assert review_target(frame, _target(), _obs(), Rect(100, 0, 50, 120),
                         captured_at=10, now=11).reason == "outside_region"
