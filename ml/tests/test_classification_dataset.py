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
