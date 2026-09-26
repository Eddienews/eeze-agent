"""Pure guard for a VLM's proposed target in one captured app window.

This module does not call a model or driver. Coordinates are image-local and MUST NOT be
passed to CUA until a separate, tested window-to-driver transform and risk gate exist.
Text observed on screen is untrusted data, never instructions for the orchestrator.
"""
from __future__ import annotations

import base64
import math
import struct
import zlib
from dataclasses import dataclass

from eeze_agent.core.models import Observation


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, x: int, y: int) -> bool:
        return self.w > 0 and self.h > 0 and self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def contains_box(self, other: Rect) -> bool:
        return (other.w > 0 and other.h > 0 and self.contains(other.x, other.y)
                and self.contains(other.x + other.w - 1, other.y + other.h - 1))


@dataclass(frozen=True)
class TargetProposal:
    pid: int
    window_id: int
    snapshot_id: str
    image_width: int
    image_height: int
    box: Rect
    x: int
    y: int
    confidence: float
    evidence: str
    alternatives: int = 0


@dataclass(frozen=True)
class TargetDecision:
    point: tuple[int, int] | None
    reason: str
    coordinate_space: str = "image-local"


def _png_dimensions(encoded: str | None) -> tuple[tuple[int, int], bytes] | None:
    if not encoded or len(encoded) > 24_000_000:
        return None
    try:
        image = base64.b64decode(encoded, validate=True)
        if (len(image) < 33 or image[:8] != b"\x89PNG\r\n\x1a\n"
                or image[8:12] != b"\0\0\0\r" or image[12:16] != b"IHDR"):
            return None
        ihdr = image[16:29]
        expected_crc = struct.unpack(">I", image[29:33])[0]
        if zlib.crc32(b"IHDR" + ihdr) != expected_crc:
            return None
        width, height = struct.unpack(">II", ihdr[:8])
        if not (0 < width <= 16_384 and 0 < height <= 16_384):
            return None
        offset, has_idat, has_end = 8, False, False
        while offset + 12 <= len(image):
            size = struct.unpack(">I", image[offset:offset + 4])[0]
            end = offset + 12 + size
            if end > len(image):
                return None
            kind = image[offset + 4:offset + 8]
            data = image[offset + 8:end - 4]
            crc = struct.unpack(">I", image[end - 4:end])[0]
            if zlib.crc32(kind + data) != crc:
                return None
            if kind == b"IDAT":
                has_idat = True
            elif kind == b"IEND":
                has_end = size == 0 and end == len(image)
                break
            offset = end
        if not (has_idat and has_end):
            return None
        return (width, height), image
    except (ValueError, struct.error):
        return None


def review_target(
    frame: Observation,
    proposal: TargetProposal | None,
    latest: Observation,
    allowed_region: Rect,
    *,
    captured_at: float,
    now: float,
) -> TargetDecision:
    """Abstain unless the window, image and single bounded target still match.

    `latest` is a recapture provided by the caller; this guard cannot certify a click,
    user interference, display scaling, or the effect of an action after it occurs.
    """
    def abstain(reason: str) -> TargetDecision:
        return TargetDecision(None, reason)

    if frame.degraded or latest.degraded:
        return abstain("degraded_capture")
    if (not frame.snapshot_id or not latest.snapshot_id
            or (frame.pid, frame.window_id) != (latest.pid, latest.window_id)):
        return abstain("identity_mismatch")
    parsed = _png_dimensions(frame.screenshot_png_b64)
    if parsed is None:
        return abstain("invalid_image")
    latest_parsed = _png_dimensions(latest.screenshot_png_b64)
    if latest_parsed is None:
        return abstain("invalid_image")
    (width, height), image = parsed
    (latest_width, latest_height), latest_image = latest_parsed
    if (width, height) != (latest_width, latest_height):
        return abstain("geometry_mismatch")
    if image != latest_image:
        return abstain("capture_changed")
    if not (math.isfinite(now) and math.isfinite(captured_at)) or now < captured_at or now - captured_at > 2.0:
        return abstain("stale_capture")
    if proposal is None:
        return abstain("no_target")
    if ((frame.pid, frame.window_id, frame.snapshot_id)
            != (proposal.pid, proposal.window_id, proposal.snapshot_id)):
        return abstain("identity_mismatch")
    if (width, height) != (proposal.image_width, proposal.image_height):
        return abstain("geometry_mismatch")
    if (not math.isfinite(proposal.confidence) or proposal.confidence < 0.9
            or proposal.alternatives != 0 or not proposal.evidence.strip()):
        return abstain("ambiguous")
    if not Rect(0, 0, width, height).contains_box(allowed_region):
        return abstain("outside_region")
    if not allowed_region.contains_box(proposal.box):
        return abstain("outside_region")
    if not proposal.box.contains(proposal.x, proposal.y):
        return abstain("point_outside_box")
    return TargetDecision((proposal.x, proposal.y), "ok")
