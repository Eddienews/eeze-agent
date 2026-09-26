"""ffmpeg/ffprobe discovery + media probing for the video vertical.

Discovery order: explicit dir → ``EEZE_FFMPEG`` (full path to ffmpeg) →
``EEZE_FFMPEG_DIR`` → ``~/tools/ffmpeg`` (direct ``bin/`` or any gyan-style extracted
tree — newest build wins) → ``PATH``. Nothing here shells out; everything is argv.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

EXE = ".exe" if os.name == "nt" else ""
_IMAGE_CODECS = {"png", "mjpeg", "bmp", "webp", "tiff", "gif"}


def find_tools(ffmpeg_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Locate ``(ffmpeg, ffprobe)``; raises FileNotFoundError with the search order."""
    if ffmpeg_dir:
        base = Path(ffmpeg_dir)
        for sub in (base / "bin", base):
            ff, fp = sub / f"ffmpeg{EXE}", sub / f"ffprobe{EXE}"
            if ff.exists() and fp.exists():
                return ff, fp
        raise FileNotFoundError(f"no ffmpeg/ffprobe under {base}")

    env_exe = os.environ.get("EEZE_FFMPEG")
    if env_exe:
        ff = Path(env_exe)
        fp = ff.with_name(f"ffprobe{EXE}")
        if ff.exists() and fp.exists():
            return ff, fp

    candidates: list[Path] = []
    env_dir = os.environ.get("EEZE_FFMPEG_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path.home() / "tools" / "ffmpeg")
    for base in candidates:
        if not base.is_dir():
            continue
        for build in sorted(base.glob("*/"), reverse=True):  # newest version dir first
            for sub in (build / "bin", build):
                ff, fp = sub / f"ffmpeg{EXE}", sub / f"ffprobe{EXE}"
                if ff.exists() and fp.exists():
                    return ff, fp
        for sub in (base / "bin", base):
            ff, fp = sub / f"ffmpeg{EXE}", sub / f"ffprobe{EXE}"
            if ff.exists() and fp.exists():
                return ff, fp

    on_path_f = shutil.which("ffmpeg")
    on_path_p = shutil.which("ffprobe")
    if on_path_f and on_path_p:
        return Path(on_path_f), Path(on_path_p)

    raise FileNotFoundError(
        "ffmpeg/ffprobe not found (tried --ffmpeg-dir, EEZE_FFMPEG, EEZE_FFMPEG_DIR, "
        "~/tools/ffmpeg, PATH) — install a static build (gyan.dev essentials) and re-run"
    )


@dataclass
class MediaInfo:
    """Facts observed with ffprobe — unknown facts stay ``None``, never 0."""

    path: str
    kind: str  # "video" | "image" | "audio" | "unknown"
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    fps: float | None = None
    codec_v: str | None = None
    codec_a: str | None = None
    has_audio: bool = False
    nb_frames: int | None = None
    size_bytes: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _fps(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = float(Fraction(raw))
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 4) if value > 0 else None


def probe(ffprobe: Path, path: Path, *, timeout_s: float = 60.0) -> MediaInfo:
    """Probe one file; raises RuntimeError when ffprobe cannot read it."""
    path = Path(path)
    proc = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed on {path}: {proc.stderr.decode('utf-8', 'replace')[:300]}"
        )
    data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = fmt.get("duration") or (video or {}).get("duration")
    try:
        duration_s = round(float(duration), 4) if duration is not None else None
    except (TypeError, ValueError):
        duration_s = None

    if video is None and audio is None:
        kind = "unknown"
    elif video is None:
        kind = "audio"
    elif "image2" in str(fmt.get("format_name") or "") or (
        str(video.get("codec_name")) in _IMAGE_CODECS and duration_s is None
    ):
        kind = "image"
    else:
        kind = "video"

    nb_frames = (video or {}).get("nb_frames")
    try:
        nb_frames_i = int(nb_frames) if nb_frames is not None else None
    except (TypeError, ValueError):
        nb_frames_i = None

    return MediaInfo(
        path=str(path),
        kind=kind,
        width=int(video["width"]) if video and video.get("width") is not None else None,
        height=int(video["height"]) if video and video.get("height") is not None else None,
        duration_s=duration_s,
        fps=_fps((video or {}).get("r_frame_rate")) or _fps((video or {}).get("avg_frame_rate")),
        codec_v=(video or {}).get("codec_name"),
        codec_a=(audio or {}).get("codec_name"),
        has_audio=audio is not None,
        nb_frames=nb_frames_i,
        size_bytes=path.stat().st_size if path.exists() else None,
    )
