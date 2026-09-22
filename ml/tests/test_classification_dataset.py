"""The classification dataset format, and the shipped seed set's honesty.

The loader refuses rather than repairs. The seed set is checked for the
provenance discipline it claims: every example traceable, every label
flagged unverified, every OCR row naming the engine that produced it.
"""

from __future__ import annotations

import copy
import json

import pytest

from labelextract.classification import taxonomy
from labelextract.classification.dataset import (
    ClassificationDataError,
    load_dataset,
    parse_dataset,
    seed_dataset_path,
)


def minimal(**overrides):
    example = {
        "example_id": "x/ocr",
        "product_id": "product_x",
        "category": "packaged-food",
        "subcategory": "general-food",
        "text": "ingredients wheat flour",
        "text_source": "ocr",
        "labelled_by": "someone",
        "label_verified_by": None,
        "ocr_engine": "tesseract",
        "ocr_engine_version": "0.3.0",
        "source_dataset": None,
        "source_sample_id": None,
        "image_sha256": None,
        "note": "",
    }
    example.update(overrides)
    return {
        "dataset_version": "t",
        "created_on": "2026-01-01",
        "description": "test",
        "taxonomy_version": taxonomy.TAXONOMY_VERSION,
        "examples": [example],
    }


def test_a_minimal_dataset_parses():
    dataset = parse_dataset(minimal())
    assert len(dataset.examples) == 1
    assert dataset.product_ids == ("product_x",)
    assert dataset.label_counts() == {"general-food": {"examples": 1, "products": 1}}
    assert not dataset.examples[0].is_verified


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.update(taxonomy_version="0"), "taxonomy"),
        (lambda d: d.update(examples=[]), "non-empty list"),
        (lambda d: d.pop("description"), "description"),
        (lambda d: d["examples"][0].update(category="packaged-thing"), "not a taxonomy category"),
        (lambda d: d["examples"][0].update(subcategory="nope"), "not a taxonomy subcategory"),
        (lambda d: d["examples"][0].update(subcategory="cleaning-product"), "does not belong"),
        (lambda d: d["examples"][0].update(text=None), "text must be a string"),
        (lambda d: d["examples"][0].update(text_source="guess"), "text_source"),
        (lambda d: d["examples"][0].pop("label_verified_by"), "label_verified_by"),
        (lambda d: d["examples"][0].update(ocr_engine=None), "must record ocr_engine"),
        (lambda d: d["examples"][0].update(image_sha256="abc"), "64 hex"),
        (lambda d: d["examples"][0].update(labelled_by=""), "labelled_by"),
        (lambda d: d["examples"].append(copy.deepcopy(d["examples"][0])), "duplicate example_id"),
    ],
)
def test_malformed_datasets_are_refused(mutate, message):
    data = minimal()
    mutate(data)
    with pytest.raises(ClassificationDataError, match=message):
        parse_dataset(data)


def test_a_transcription_needs_no_engine():
    data = minimal(text_source="manual_transcription", ocr_engine=None, ocr_engine_version=None)
    assert parse_dataset(data).examples[0].ocr_engine is None


def test_empty_text_is_allowed_because_it_happens():
    """A front panel OCR read as nothing is a real outcome worth keeping."""
    assert parse_dataset(minimal(text="")).examples[0].text == ""


def test_load_dataset_reports_missing_and_invalid_files(tmp_path):
    with pytest.raises(ClassificationDataError, match="could not be read"):
        load_dataset(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_bytes(b"\xff\xfe not json")
    with pytest.raises(ClassificationDataError, match="UTF-8 JSON"):
        load_dataset(broken)


def test_load_dataset_records_the_file_digest(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(json.dumps(minimal()), encoding="utf-8")
    dataset = load_dataset(path)
    assert len(dataset.sha256) == 64
    assert dataset.path == path


def test_a_dataset_written_before_the_verification_fields_still_parses():
    """The two fields added for verification are optional and default to null.

    `seed_v0.1.json` predates them and is frozen - `tfidf-logreg 0.1.0` records
    its digest - so a schema change that required them would have invalidated
    the only dataset the project has.
    """
    data = minimal()
    data["examples"][0].pop("label_verified_on", None)
    data["examples"][0].pop("label_verification_ref", None)
    example = parse_dataset(data).examples[0]
    assert example.label_verified_on is None
    assert example.label_verification_ref is None
    assert not example.is_verified


# --- the shipped seed set -----------------------------------------------------


@pytest.fixture(scope="module")
def seed():
    return load_dataset()


def test_seed_set_loads_from_the_package(seed):
    assert seed.path == seed_dataset_path()
    assert seed.dataset_version == "product-classification-seed-v0.1"


def test_seed_set_is_ten_products_and_says_so(seed):
    assert len(seed.product_ids) == 10
    assert len(seed.examples) == 33
    assert "NOT human-verified" in seed.description
    assert "too few" in seed.description


def test_every_seed_label_is_flagged_unverified(seed):
    """Nobody has checked these labels, and no row may claim otherwise."""
    assert all(example.label_verified_by is None for example in seed.examples)
    assert all("draft" in example.labelled_by for example in seed.examples)


def test_every_seed_example_is_traceable_to_a_frozen_photograph(seed):
    for example in seed.examples:
        assert example.source_dataset == "our-eval-v0.1-draft"
        assert example.source_sample_id
        assert example.image_sha256 and len(example.image_sha256) == 64


def test_every_ocr_row_names_the_pipeline_that_read_it(seed):
    ocr_rows = [e for e in seed.examples if e.text_source == "ocr"]
    assert len(ocr_rows) == 28
    assert {(e.ocr_engine, e.ocr_engine_version) for e in ocr_rows} == {("tesseract", "0.3.0")}


def test_every_transcription_says_a_model_wrote_it(seed):
    rows = [e for e in seed.examples if e.text_source == "manual_transcription"]
    assert len(rows) == 5
    assert all("not verified" in e.note for e in rows)


def test_seed_class_distribution_is_what_the_docs_say(seed):
    assert seed.label_counts() == {
        "cleaning-product": {"examples": 7, "products": 1},
        "cosmetics-and-toiletries": {"examples": 5, "products": 1},
        "general-food": {"examples": 16, "products": 7},
        "health-supplement": {"examples": 5, "products": 1},
    }


def test_seed_set_contains_no_secret_looking_strings(seed):
    """Label text is public print; nothing else may be in here."""
    blob = json.dumps([e.text for e in seed.examples]).lower()
    for marker in ("api_key", "secret", "password", "token=", "bearer "):
        assert marker not in blob


# --- the digest is the content, not the checkout -----------------------------


def test_the_digest_is_independent_of_line_endings(tmp_path):
    """The same dataset checked out with LF (CI) and CRLF (a Windows working
    copy under core.autocrlf=true) must have one digest, or the artifact's
    recorded dataset can disagree with the dataset while both are unchanged
    - which is exactly the CI failure this test exists to prevent."""
    import hashlib

    body = json.dumps(minimal(), indent=2)
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(body.encode("utf-8"))
    crlf.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
    assert lf.read_bytes() != crlf.read_bytes()

    assert load_dataset(lf).sha256 == load_dataset(crlf).sha256
    assert load_dataset(lf).sha256 == hashlib.sha256(lf.read_bytes()).hexdigest()


def test_the_digest_of_the_seed_set_is_the_digest_of_its_lf_bytes(seed):
    """Whatever line endings this checkout has, the seed digest is the
    SHA-256 of the file as Git stores it."""
    import hashlib

    raw = seed_dataset_path().read_bytes().replace(b"\r\n", b"\n")
    assert seed.sha256 == hashlib.sha256(raw).hexdigest()


# --- the dataset registry ------------------------------------------------------
#
# A published dataset version is immutable once an artifact has been trained
# against it. The registry is what makes that enforceable rather than a note in
# a README: it records the digest of every version, and these tests re-digest
# the files and refuse a mismatch. Edit a trained-against dataset and the
# failure is here, rather than in the quiet difference between what a published
# number meant and what it now means.


@pytest.fixture(scope="module")
def registry():
    path = seed_dataset_path().parent / "REGISTRY.json"
    return json.loads(path.read_text(encoding="utf-8")), path


def test_every_registered_dataset_file_exists_and_matches_its_digest(registry):
    document, path = registry
    assert document["datasets"], "the registry must list every published version"
    for row in document["datasets"]:
        dataset = load_dataset(path.parent / row["file"])
        assert dataset.sha256 == row["sha256"], row["file"]
        assert dataset.dataset_version == row["dataset_version"]


def test_every_registered_row_states_its_own_composition(registry):
    """The counts in the registry are derived from the file, not typed at it."""
    document, path = registry
    for row in document["datasets"]:
        dataset = load_dataset(path.parent / row["file"])
        assert row["examples"] == len(dataset.examples)
        assert row["products"] == len(dataset.product_ids)
        assert row["images"] == len(dataset.image_sha256s)
        assert row["verified_examples"] == len(dataset.verified_examples)
        assert row["taxonomy_version"] == dataset.taxonomy_version


def test_dataset_versions_are_unique_in_the_registry(registry):
    document, _ = registry
    versions = [row["dataset_version"] for row in document["datasets"]]
    assert len(versions) == len(set(versions))


def test_the_seed_set_is_registered_as_the_artifacts_training_data(seed, registry):
    """The link the artifact records from the other end."""
    document, _ = registry
    row = next(
        item
        for item in document["datasets"]
        if item["dataset_version"] == seed.dataset_version
    )
    assert row["sha256"] == seed.sha256
    assert "tfidf-logreg/0.1.0" in row["trained_artifacts"]


def test_changing_a_dataset_changes_its_digest(tmp_path):
    """What 'a new digest per dataset change' means, asserted rather than assumed."""
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    document = minimal()
    before.write_text(json.dumps(document, indent=2), encoding="utf-8")
    document["examples"][0]["subcategory"] = "health-supplement"
    after.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert load_dataset(before).sha256 != load_dataset(after).sha256
