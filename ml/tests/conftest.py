"""Shared fixtures.

These build real files on disk rather than mocks, so the tests exercise the
same code paths the backend will.
"""

import struct
import zlib
from pathlib import Path

import pytest

from labelextract.contracts import ImageRef


def _minimal_png(width: int = 4, height: int = 4) -> bytes:
    """Build a valid single-colour PNG without depending on an image library.

    `ml/` has no runtime dependencies by design, and the tests must not
    introduce one. This produces a genuinely decodable PNG - it is used by the
    backend's validator tests too, where Pillow really does decode it.
    """

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    # Bit depth 8, colour type 2 (truecolour), no interlace.
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # Each scanline is a filter byte followed by RGB triples.
    scanlines = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def png_path(tmp_path: Path) -> Path:
    """A small, valid PNG file on disk."""
    path = tmp_path / "label.png"
    path.write_bytes(_minimal_png())
    return path


@pytest.fixture
def image_ref(png_path: Path) -> ImageRef:
    return ImageRef(
        path=png_path,
        image_format="png",
        size_bytes=png_path.stat().st_size,
        width=4,
        height=4,
    )
