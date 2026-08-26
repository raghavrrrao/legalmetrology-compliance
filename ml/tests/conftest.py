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


@pytest.fixture
def ocr_lines():
    """Build an `OcrResult` from plain lines, as a line-oriented engine would.

    The OCR engine is deliberately never involved in field-extraction tests: a
    test that had to run Tesseract would fail on a machine without it and would
    be measuring recognition rather than interpretation. Boxes are synthesised
    on a regular grid so a test can still assert that geometry survives the
    trip from a block to an extracted field.
    """
    from labelextract.contracts import BoundingBox, OcrResult, TextBlock

    def _make(lines, *, confidence: float | None = 0.9) -> OcrResult:
        return OcrResult(
            blocks=tuple(
                TextBlock(
                    text=text,
                    box=BoundingBox(x=1, y=1 + index * 20, width=300, height=18),
                    confidence=confidence,
                )
                for index, text in enumerate(lines)
            ),
            raw={"fake": True},
        )

    return _make


@pytest.fixture
def tesseract_data():
    """Build pytesseract-shaped word columns from (text, confidence) lines.

    Mirrors `image_to_data(output_type=DICT)`: parallel lists, one row per
    layout element, with -1 confidence on the rows that carry no text.
    """

    def _make(lines) -> dict:
        columns = {
            key: []
            for key in (
                "level", "page_num", "block_num", "par_num", "line_num",
                "word_num", "left", "top", "width", "height", "conf", "text",
            )
        }

        def row(**values):
            for key in columns:
                columns[key].append(values.get(key, 0))

        # A page row, as Tesseract emits, with no text and no confidence.
        row(level=1, page_num=1, conf=-1, text="", width=800, height=600)

        for line_number, (text, confidence) in enumerate(lines, start=1):
            top = line_number * 30
            for word_number, word in enumerate(text.split(), start=1):
                row(
                    level=5,
                    page_num=1,
                    block_num=1,
                    par_num=1,
                    line_num=line_number,
                    word_num=word_number,
                    left=10 + (word_number - 1) * 60,
                    top=top,
                    width=55,
                    height=20,
                    conf=confidence,
                    text=word,
                )
        return columns

    return _make
