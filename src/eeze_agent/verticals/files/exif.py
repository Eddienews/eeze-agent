"""Minimal, dependency-free reader for a JPEG's "date taken" (EXIF DateTimeOriginal).

Only what the files vertical needs: returns a ``datetime`` or ``None``. Never raises.
"""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path

_DATE_TAGS = (0x9003, 0x9004, 0x0132)  # DateTimeOriginal, DateTimeDigitized, DateTime


def _parse_ifd(tiff: bytes, offset: int, endian: str, found: dict[int, str], depth: int = 0) -> None:
    if depth > 3 or offset + 2 > len(tiff):
        return
    (count,) = struct.unpack_from(endian + "H", tiff, offset)
    for i in range(min(count, 512)):
        entry = offset + 2 + i * 12
        if entry + 12 > len(tiff):
            return
        tag, kind, n, value = struct.unpack_from(endian + "HHII", tiff, entry)
        if tag == 0x8769:  # Exif sub-IFD pointer
            _parse_ifd(tiff, value, endian, found, depth + 1)
        elif tag in _DATE_TAGS and kind == 2 and n >= 19:
            start = value if n > 4 else entry + 8
            raw = tiff[start:start + 19]
            try:
                found[tag] = raw.decode("ascii")
            except UnicodeDecodeError:
                pass


def date_taken(path: str | Path) -> datetime | None:
    try:
        with Path(path).open("rb") as fh:
            data = fh.read(256 * 1024)  # EXIF lives in the first blocks; never read the whole file
    except (OSError, MemoryError):
        return None
    if data[:2] != b"\xff\xd8":
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        (size,) = struct.unpack_from(">H", data, pos + 2)
        if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\x00\x00":
            tiff = data[pos + 10:pos + 2 + size]
            endian = "<" if tiff[:2] == b"II" else ">"
            try:
                (ifd0,) = struct.unpack_from(endian + "I", tiff, 4)
                found: dict[int, str] = {}
                _parse_ifd(tiff, ifd0, endian, found)
            except struct.error:
                return None
            for tag in _DATE_TAGS:
                if tag in found:
                    try:
                        return datetime.strptime(found[tag], "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
            return None
        if marker in (0xDA, 0xD9):  # start of scan / end: no EXIF before the image data
            return None
        pos += 2 + size
    return None
