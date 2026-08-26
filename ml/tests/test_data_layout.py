"""The local image directory: it exists, it is ignored, and the CLI reads it.

`ml/data/` is where a developer drops real photographs of packaged commodities
to run the pipeline by hand. Two properties of it are worth a test, because
both fail silently:

1. **The scaffolding survives.** An empty directory does not exist in Git on
   its own; it exists because of a `.gitkeep`. Delete one in a cleanup pass and
   the next clone has nowhere documented to put images.
2. **Images stay out of Git.** `.gitignore` ignores everything under
   `ml/data/` and then re-includes the README and the placeholders. That is a
   negation chain, and a later edit to any line of it can quietly start
   tracking photographs - which, once committed, are in every clone for ever.

Nothing here measures OCR. No image ships with the repository, so there is
nothing to recognise and no accuracy to claim.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from labelextract.baseline import null_engine
from labelextract.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "ml" / "data"

#: The layout ml/data/README.md documents. Kept as a literal list rather than
#: derived from the filesystem: a test that reads the directories it is meant
#: to be asserting the existence of would pass on an empty tree.
DOCUMENTED_DIRECTORIES = (
    "raw/products",
    "evaluation/compliant",
    "evaluation/non_compliant",
    "evaluation/requires_review",
)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


requires_git = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO_ROOT / ".git").exists(),
    reason="not a Git checkout with git available - nothing to ask about ignores",
)


def test_the_documented_directories_exist():
    missing = [
        name
        for name in DOCUMENTED_DIRECTORIES
        if not (DATA_ROOT / name).is_dir()
    ]
    assert not missing, f"ml/data/README.md documents directories that are gone: {missing}"


def test_each_directory_is_held_open_by_a_placeholder():
    """Git stores no empty directory. Without these, a clone has none of them."""
    missing = [
        name
        for name in DOCUMENTED_DIRECTORIES
        if not (DATA_ROOT / name / ".gitkeep").is_file()
    ]
    assert not missing, f"missing .gitkeep, so these vanish on a fresh clone: {missing}"


def test_the_directory_documents_itself():
    readme = DATA_ROOT / "README.md"
    assert readme.is_file(), "ml/data/README.md is what tells a developer where images go"


@requires_git
@pytest.mark.parametrize(
    "relative_path",
    [
        "raw/products/product_0001_front.jpg",
        "raw/products/product_0001_back.png",
        "evaluation/compliant/eval_0001_compliant_front.jpg",
        "evaluation/non_compliant/eval_0002_non_compliant_back.jpg",
        "evaluation/requires_review/eval_0003_requires_review.webp",
        "evaluation/compliant/annotations.json",
    ],
)
def test_a_file_dropped_into_the_data_directory_is_ignored(relative_path):
    """The paths in the README, checked against the real ignore rules.

    `--no-index` so the answer does not depend on whether such a file happens
    to exist on this machine, and plain `check-ignore` rather than `-v`: with
    `-v` a matched *negation* also exits 0, which would make this pass on
    exactly the mistake it exists to catch.
    """
    result = _git("check-ignore", "--no-index", "--quiet", f"ml/data/{relative_path}")
    assert result.returncode == 0, (
        f"ml/data/{relative_path} is NOT ignored by Git. A product photograph "
        f"committed here is in every clone permanently - see .gitignore."
    )


@requires_git
@pytest.mark.parametrize(
    "relative_path",
    ["README.md", *(f"{name}/.gitkeep" for name in DOCUMENTED_DIRECTORIES)],
)
def test_the_scaffolding_itself_is_not_ignored(relative_path):
    """The other half: over-broad ignores would drop the structure from a clone."""
    result = _git("check-ignore", "--no-index", "--quiet", f"ml/data/{relative_path}")
    assert result.returncode == 1, (
        f"ml/data/{relative_path} is ignored, so a fresh clone would not get it."
    )


@requires_git
def test_no_image_has_been_committed_under_the_data_directory():
    """The safety net checked directly, rather than trusting the rules above."""
    result = _git("ls-files", "--", "ml/data")
    if result.returncode != 0:  # pragma: no cover - only when git refuses to run
        pytest.skip(f"git ls-files unavailable: {result.stderr.strip()}")

    tracked = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    allowed = {"ml/data/README.md"} | {
        f"ml/data/{name}/.gitkeep" for name in DOCUMENTED_DIRECTORIES
    }
    assert tracked <= allowed, (
        f"unexpected tracked files under ml/data: {sorted(tracked - allowed)}"
    )


@requires_git
def test_the_documented_cli_command_accepts_a_path_in_the_data_directory(capsys):
    """`python -m labelextract.cli ml/data/raw/products/<file>` resolves and runs.

    The point is the *path*, not recognition: the null-engine pipeline reads no
    pixels, so this asserts the CLI accepts a file living in the real directory
    from the repository root and says nothing whatever about OCR quality.

    The probe is written into `raw/products/` rather than a tmp directory
    precisely because that is the path being tested, and it is removed again.
    It is git-ignored either way - `test_a_file_dropped_into_the_data_directory
    _is_ignored` is what guarantees that.
    """
    probe = DATA_ROOT / "raw" / "products" / f"_pytest_probe_{os.getpid()}.png"
    assert not probe.exists(), f"stale probe from an earlier run: {probe}"
    probe.write_bytes(_minimal_png_bytes())

    original_cwd = Path.cwd()
    try:
        os.chdir(REPO_ROOT)
        relative = f"ml/data/raw/products/{probe.name}"
        exit_code = main([relative, "--pipeline", str(null_engine.NAME)])
    finally:
        os.chdir(original_cwd)
        probe.unlink(missing_ok=True)

    # 1 is EMPTY: the placeholder engine recognises nothing, by design. What
    # matters is that it is not 3 - the exit code for an unusable argument.
    assert exit_code == 1
    assert null_engine.NAME in capsys.readouterr().out


def _minimal_png_bytes(width: int = 4, height: int = 4) -> bytes:
    """The same byte-by-byte PNG `conftest.png_path` builds, without a tmp_path.

    Duplicated rather than shared because the fixture returns a file in pytest's
    temporary directory, and the whole point of this test is the file's
    location.
    """
    import struct
    import zlib

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
