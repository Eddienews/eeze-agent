"""ffmpeg argv builders for the video vertical's operations.

Pure builders (no execution): the runner owns running and verifying. Encode settings
are fixed for reproducibility (h264 yuv420p, veryfast) — a spec cannot ask for something
the verification does not understand. No shell anywhere: every call is an argv list.
"""

from __future__ import annotations

from pathlib import Path

PRESET = "veryfast"
DEFAULT_FPS = 25.0
SAMPLE_RATE = "44100"


def _base(ff: Path, *args: str) -> list[str]:
    return [str(ff), "-y", "-hide_banner", "-loglevel", "error", *args]


def fit_filter(size: tuple[int, int], *, color: str = "black") -> str:
    """Contain the frame inside ``size`` and pad the rest (aspect preserved)."""
    w, h = size
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}"
    )


def fill_filter(size: tuple[int, int]) -> str:
    """Cover the whole frame, cropping the overflow from the center (aspect preserved).

    What Reels/Shorts/TikTok expect: a horizontal clip becomes a full-height vertical one
    (sides cropped) instead of a small strip between black bars.
    """
    w, h = size
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def size_filter(size: tuple[int, int], fit: str) -> str:
    if fit == "fill":
        return fill_filter(size)
    if fit == "stretch":
        return f"scale={size[0]}:{size[1]},setsar=1"
    return fit_filter(size)


def op_still_to_video(
    ff: Path, *, src: Path, dst: Path, duration: float, size: tuple[int, int], fps: float,
    fit: str = "fit",
) -> list[str]:
    """An image becomes a video of ``duration`` seconds with silent audio.

    NOTE: ``-t`` must be an OUTPUT option here. As an input option it mis-times the
    looped image when a second (anullsrc) input is present — measured live: asked 0.6 s,
    got 0.998 s; output-side ``-t`` yields exactly 0.600 s.
    """
    return _base(
        ff,
        "-loop", "1", "-framerate", str(fps), "-i", str(src),
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}",
        "-t", str(duration),
        "-vf", size_filter(size, fit),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", PRESET,
        "-c:a", "aac",
        str(dst),
    )


def op_trim(ff: Path, *, src: Path, dst: Path, start: float, duration: float) -> list[str]:
    """Accurate re-encoded cut: input seek + decode/discard to the exact start."""
    return _base(
        ff,
        "-ss", str(start), "-i", str(src), "-t", str(duration),
        "-c:v", "libx264", "-preset", PRESET, "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-avoid_negative_ts", "make_zero",
        str(dst),
    )


def op_scale(ff: Path, *, src: Path, dst: Path, size: tuple[int, int], fit: str) -> list[str]:
    vf = size_filter(size, fit)
    return _base(
        ff,
        "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", PRESET, "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(dst),
    )


def op_fps(ff: Path, *, src: Path, dst: Path, rate: float) -> list[str]:
    return _base(
        ff,
        "-i", str(src),
        "-vf", f"fps={rate}",
        "-c:v", "libx264", "-preset", PRESET, "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(dst),
    )


def op_normalize(
    ff: Path,
    *,
    src: Path,
    dst: Path,
    size: tuple[int, int],
    fps: float,
    has_audio: bool,
    duration: float,
) -> list[str]:
    """Common shape for concat: size/fps/sar + h264/aac; silent inputs get a silent track.

    ``-t`` is an OUTPUT option on purpose: with an infinite anullsrc input, ``-shortest``
    overshoots the video end (measured live: a 0.6 s silent clip came out 0.998 s at the
    container level); output-side ``-t`` trims every stream to the measured source
    duration, which is exactly what a concat join needs.
    """
    args = [str(ff), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if not has_audio:
        args += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}"]
    args += [
        "-vf", f"{fit_filter(size)},fps={fps},setsar=1",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", PRESET, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", SAMPLE_RATE, "-ac", "2",
        str(dst),
    ]
    return args


def op_concat(ff: Path, *, list_file: Path, dst: Path) -> list[str]:
    """Concat demuxer over already-normalized files (stream copy, no re-encode)."""
    return _base(
        ff,
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(dst),
    )


def op_thumbnail(ff: Path, *, src: Path, dst: Path, at: float) -> list[str]:
    return _base(ff, "-ss", str(at), "-i", str(src), "-frames:v", "1", str(dst))
