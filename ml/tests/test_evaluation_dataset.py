"""The frozen dataset: what loads, what is refused, and why refusal matters.

Every fixture here is **synthetic** - a manifest and annotations written by the
test, over PNGs built byte-by-byte. They exercise the infrastructure and they
are not a measurement of anything. No real photograph and no real annotation
exists in this repository; `ml/data/` is git-ignored in full and
`test_data_layout.py` asserts it stays that way.

The bar these tests defend: **ground truth is refused rather than repaired.**
Several tests below assert that loading *fails*, and they are the important
ones. A dataset that loads with three bad samples quietly dropped still reports
a sample count, and that count is what ends up in the report.
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import pytest

from labelextract.contracts import LabelFieldKey
from labelextract.evaluation import (
    EvaluationDataError,
    FieldTruthState,
    describe_dataset,
    file_sha256,
    load_dataset,
    load_manifest,
)


def _png_bytes(width: int = 4, height: int = 4, grey: int = 0x80) -> bytes:
    """A genuinely decodable PNG, built without an image library."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(
        b"\x00" + bytes((grey, grey, grey)) * width for _ in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def build_dataset(tmp_path):
    """Write a synthetic frozen dataset to disk and return its root."""

    def _build(
        samples: list[dict] | None = None,
        *,
        dataset_version: str = "v1",
        created_on: str = "2026-01-15",
        manifest_overrides: dict | None = None,
        write_images: bool = True,
    ) -> Path:
        root = tmp_path / "our-evaluation-set"
        (root / "images").mkdir(parents=True, exist_ok=True)
        (root / "annotations").mkdir(parents=True, exist_ok=True)

        samples = samples if samples is not None else [_sample_spec("eval_0001")]
        entries = []
        for spec in samples:
            sample_id = spec["sample_id"]
            image_rel = f"images/{sample_id}.png"
            annotation_rel = f"annotations/{sample_id}.json"

            payload = _png_bytes(grey=spec.get("grey", 0x80))
            if write_images:
                (root / image_rel).write_bytes(payload)

            (root / annotation_rel).write_text(
                json.dumps(spec["annotation"], indent=2), encoding="utf-8"
            )
            entries.append(
                {
                    "sample_id": sample_id,
                    "image": image_rel,
                    "annotation": annotation_rel,
                    "image_sha256": spec.get(
                        "sha256",
                        file_sha256(root / image_rel) if write_images else "0" * 64,
                    ),
                }
            )

        manifest = {
            "dataset_version": dataset_version,
            "created_on": created_on,
            "description": "Synthetic fixture. Not a measurement.",
            "samples": entries,
        }
        manifest.update(manifest_overrides or {})
        (root / "MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return root

    return _build


def _sample_spec(sample_id: str, **annotation_overrides) -> dict:
    annotation = {
        "sample_id": sample_id,
        "annotated_by": "a-reviewer",
        "annotated_on": "2026-01-15",
        "conditions": ["flat", "good_light"],
        "fields": [
            {
                "key": "net_quantity",
                "state": "present_and_readable",
                "value": "500 g",
            }
        ],
    }
    annotation.update(annotation_overrides)
    return {"sample_id": sample_id, "annotation": annotation}


# --- the happy path ----------------------------------------------------------


def test_a_well_formed_dataset_loads(build_dataset):
    dataset = load_dataset(build_dataset())

    assert dataset.dataset_version == "v1"
    assert len(dataset) == 1
    sample = dataset.sample("eval_0001")
    assert sample.annotation.annotated_by == "a-reviewer"
    assert sample.image_path.is_file()


def test_the_description_carries_dataset_identity(build_dataset):
    """A report embeds this, because a number without its dataset is not a claim."""
    description = describe_dataset(load_dataset(build_dataset()))

    assert description["dataset_version"] == "v1"
    assert description["created_on"] == "2026-01-15"
    assert description["sample_count"] == 1
    assert description["annotated_field_count"] == 1
    assert description["conditions"] == {"flat": 1, "good_light": 1}


def test_an_empty_manifest_is_valid_and_measures_nothing(build_dataset):
    """Valid and useless are different states, and both are legitimate.

    A frozen set is created before it is filled. Refusing to load an empty one
    would make the natural first step an error; pretending it can measure
    something would be worse.
    """
    dataset = load_dataset(build_dataset(samples=[]))
    assert len(dataset) == 0
    assert describe_dataset(dataset)["sample_count"] == 0


# --- refusal: identity and structure ----------------------------------------


def test_a_duplicate_sample_id_is_refused(build_dataset):
    """A duplicated sample is counted twice in every metric it touches."""
    root = build_dataset(
        samples=[_sample_spec("eval_0001"), _sample_spec("eval_0001")]
    )
    with pytest.raises(EvaluationDataError, match="duplicate sample_id"):
        load_dataset(root)


def test_a_missing_manifest_field_is_refused(build_dataset):
    root = build_dataset(manifest_overrides={"dataset_version": ""})
    with pytest.raises(EvaluationDataError, match="dataset_version"):
        load_dataset(root)


@pytest.mark.parametrize(
    "version", ["", "v 1", "../escape", "v1/../v2", "a" * 65]
)
def test_an_unusable_dataset_version_is_refused(build_dataset, version):
    root = build_dataset(manifest_overrides={"dataset_version": version})
    with pytest.raises(EvaluationDataError):
        load_dataset(root)


def test_a_non_iso_created_on_is_refused(build_dataset):
    """"Last Tuesday" is not a date a later reader can check a claim against."""
    root = build_dataset(manifest_overrides={"created_on": "last Tuesday"})
    with pytest.raises(EvaluationDataError, match="created_on"):
        load_dataset(root)


def test_an_absolute_or_escaping_image_path_is_refused(build_dataset, tmp_path):
    root = build_dataset()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["samples"][0]["image"] = "../../../etc/passwd"
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvaluationDataError, match="relative path"):
        load_dataset(root)


@pytest.mark.parametrize(
    "hostile",
    [
        "../etc/passwd",
        "/absolute/path.png",
        "images/../../escape.png",
        # Found in review: the guard split on "/" only, so a backslash path
        # contained no ".." segment by that reckoning and was accepted - and on
        # Windows, where most of this team develops, `root / that` really does
        # resolve outside the dataset.
        "..\\..\\windows\\system32",
        "images\\..\\..\\escape.png",
    ],
)
def test_a_manifest_path_escaping_the_dataset_is_refused(build_dataset, hostile):
    """A manifest may only reference files inside its own dataset."""
    root = build_dataset()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["samples"][0]["image"] = hostile
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvaluationDataError):
        load_dataset(root)


def test_a_symlink_out_of_the_dataset_is_refused(build_dataset, tmp_path):
    """The string checks catch what looks like an escape; this catches what is one."""
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png_bytes())

    root = build_dataset()
    link = root / "images" / "linked.png"
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this platform/account cannot create symlinks")

    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["samples"][0]["image"] = "images/linked.png"
    (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvaluationDataError, match="outside the dataset root"):
        load_dataset(root)


def test_a_missing_image_is_refused_not_skipped(build_dataset):
    """Skipping it would shrink the set silently and still report a count."""
    root = build_dataset(write_images=False)
    with pytest.raises(EvaluationDataError, match="image is missing"):
        load_dataset(root)


def test_an_annotation_whose_sample_id_disagrees_is_refused(build_dataset):
    """Otherwise one label's truth is scored against another label's image."""
    spec = _sample_spec("eval_0001")
    spec["annotation"]["sample_id"] = "eval_0002"
    with pytest.raises(EvaluationDataError, match="declares sample_id"):
        load_dataset(build_dataset(samples=[spec]))


def test_malformed_json_is_refused(build_dataset):
    root = build_dataset()
    (root / "annotations" / "eval_0001.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(EvaluationDataError, match="not valid JSON"):
        load_dataset(root)


def test_a_missing_dataset_root_is_refused(tmp_path):
    with pytest.raises(EvaluationDataError, match="does not exist"):
        load_dataset(tmp_path / "nope")


# --- refusal: the frozen guarantee ------------------------------------------


def test_an_image_whose_bytes_changed_is_refused(build_dataset):
    """This is what makes "frozen" a fact rather than an intention.

    Editing a photograph in place would silently change what every number
    already published against this version meant. The digest catches it, and
    the message says what to do instead: publish a new version.
    """
    root = build_dataset()
    (root / "images" / "eval_0001.png").write_bytes(_png_bytes(grey=0x10))

    with pytest.raises(EvaluationDataError, match="does not match the manifest digest"):
        load_dataset(root)


def test_the_checksum_failure_names_the_remedy(build_dataset):
    root = build_dataset()
    (root / "images" / "eval_0001.png").write_bytes(_png_bytes(grey=0x10))

    with pytest.raises(EvaluationDataError) as caught:
        load_dataset(root)
    assert "new dataset_version" in str(caught.value)


def test_checksum_verification_can_be_skipped_only_explicitly(build_dataset):
    """The escape hatch exists for a re-check in one process, and is opt-in."""
    root = build_dataset()
    (root / "images" / "eval_0001.png").write_bytes(_png_bytes(grey=0x10))

    with pytest.raises(EvaluationDataError):
        load_dataset(root)
    assert len(load_dataset(root, verify_checksums=False)) == 1


@pytest.mark.parametrize("digest", ["", "abc", "A" * 64, "z" * 64])
def test_a_malformed_digest_is_refused(build_dataset, digest):
    spec = _sample_spec("eval_0001")
    spec["sha256"] = digest
    with pytest.raises(EvaluationDataError, match="image_sha256"):
        load_dataset(build_dataset(samples=[spec]))


def test_load_manifest_does_not_need_the_samples_present(build_dataset):
    """Reading identity is cheap and must not require the images."""
    root = build_dataset(write_images=False)
    manifest = load_manifest(root)
    assert manifest.dataset_version == "v1"
    assert manifest.sample_count == 1
