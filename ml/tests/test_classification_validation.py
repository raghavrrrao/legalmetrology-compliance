"""Data-integrity checks over a classification dataset.

Each check gets a test that builds the exact defect it exists to catch, and
one that confirms a clean dataset does not trip it. The shipped seed set is
then held to the whole battery, which it passes with warnings and no errors -
that is the honest state of it, and a test that demanded zero warnings would
be a test that the project had no data problem.

A defect here is not hypothetical. Every one of these has a way of arriving
through an ordinary edit: a product imported twice under two ids, a panel
pasted into the file a second time, a label corrected on one row and not its
siblings. None is caught by the schema, and each moves a measured number
upwards.
"""

from __future__ import annotations

import copy
import json

import pytest

from labelextract.classification import taxonomy, validation
from labelextract.classification.dataset import (
    ClassificationDataError,
    load_dataset,
    parse_dataset,
)
from labelextract.classification.validation import (
    DatasetIntegrityError,
    ERROR,
    WARNING,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def example(**overrides):
    """One well-formed example. Override exactly what a test is about."""
    row = {
        "example_id": "p001_01/ocr",
        "product_id": "product_001",
        "category": "packaged-food",
        "subcategory": "general-food",
        "text": "ingredients wheat flour sugar salt",
        "text_source": "ocr",
        "labelled_by": "someone-draft",
        "label_verified_by": None,
        "label_verified_on": None,
        "label_verification_ref": None,
        "ocr_engine": "tesseract",
        "ocr_engine_version": "0.3.0",
        "source_dataset": "our-eval-v0.1-draft",
        "source_sample_id": "p001_01",
        "image_sha256": DIGEST_A,
        "note": "front panel",
    }
    row.update(overrides)
    return row


def dataset_of(*examples):
    return parse_dataset(
        {
            "dataset_version": "t",
            "created_on": "2026-01-01",
            "description": "test",
            "taxonomy_version": taxonomy.TAXONOMY_VERSION,
            "examples": list(examples),
        }
    )


def codes(findings, severity=None):
    return sorted(
        finding.code
        for finding in findings
        if severity is None or finding.severity == severity
    )


@pytest.fixture
def seed():
    return load_dataset()


# --- a clean dataset trips nothing it should not ------------------------------


def test_a_clean_two_product_dataset_raises_no_errors():
    data = dataset_of(
        example(),
        example(example_id="p001_02/ocr", source_sample_id="p001_02", image_sha256=DIGEST_B,
                text="net quantity 500 g mrp rs 149"),
        example(example_id="p002_01/ocr", product_id="product_002", source_sample_id="p002_01",
                image_sha256=DIGEST_C, text="shampoo conditioner for dry hair",
                category="packaged-non-food", subcategory="cosmetics-and-toiletries"),
    )
    findings = validation.validate(data)
    assert validation.errors(findings) == ()


def test_raise_for_errors_is_silent_when_there_are_none():
    validation.raise_for_errors(validation.validate(dataset_of(example())))


# --- 2, 3: the same package, or the same reading, counted twice ---------------


def test_one_photograph_under_two_product_ids_is_a_duplicate_product():
    """One image can only have been taken of one package."""
    findings = validation.check_duplicate_products(
        dataset_of(
            example(),
            example(example_id="other/ocr", product_id="product_999"),
        )
    )
    assert codes(findings) == ["duplicate-product"]
    assert findings[0].severity == ERROR
    assert set(findings[0].subjects) == {"product_001", "product_999"}


def test_the_same_image_and_text_source_twice_is_a_duplicate_reading():
    findings = validation.check_duplicate_images(
        dataset_of(example(), example(example_id="p001_01/ocr-again", text="different"))
    )
    assert codes(findings) == ["duplicate-image"]


def test_one_image_may_carry_both_an_ocr_row_and_a_transcription():
    """The seed set does exactly this, deliberately: they are different data."""
    findings = validation.check_duplicate_images(
        dataset_of(
            example(),
            example(
                example_id="p001_01/transcription",
                text_source="manual_transcription",
                ocr_engine=None,
                ocr_engine_version=None,
                text="INGREDIENTS: Wheat flour, sugar, salt",
            ),
        )
    )
    assert findings == []


# --- 6: provenance ------------------------------------------------------------


@pytest.mark.parametrize("field", ["source_dataset", "source_sample_id", "image_sha256"])
def test_an_example_that_cannot_be_traced_to_a_photograph_is_an_error(field):
    findings = validation.check_provenance(dataset_of(example(**{field: None})))
    assert codes(findings) == ["missing-provenance"]
    assert field in findings[0].message


def test_ocr_text_must_name_the_engine_that_read_it():
    """Constructed past the loader, which refuses this too - defence in depth."""
    data = dataset_of(example())
    broken = data.examples[0].__class__(
        **{**data.examples[0].__dict__, "ocr_engine": None}
    )
    findings = validation.check_provenance(
        data.__class__(**{**data.__dict__, "examples": (broken,)})
    )
    assert "missing-ocr-provenance" in codes(findings)


# --- 8: one package is one kind of product ------------------------------------


def test_two_subcategories_on_one_product_conflict():
    findings = validation.check_conflicting_labels(
        dataset_of(
            example(),
            example(
                example_id="p001_02/ocr",
                image_sha256=DIGEST_B,
                subcategory="health-supplement",
            ),
        )
    )
    assert codes(findings) == ["conflicting-label"]
    assert "general-food" in findings[0].message


def test_two_categories_on_one_product_conflict():
    findings = validation.check_conflicting_labels(
        dataset_of(
            example(),
            example(
                example_id="p001_02/ocr",
                image_sha256=DIGEST_B,
                category="packaged-non-food",
                subcategory="cleaning-product",
            ),
        )
    )
    assert "conflicting-label" in codes(findings)


# --- 11: the same text twice --------------------------------------------------


def test_identical_text_under_two_products_is_an_error():
    findings = validation.check_duplicate_text(
        dataset_of(
            example(),
            example(
                example_id="p002_01/ocr",
                product_id="product_002",
                image_sha256=DIGEST_B,
            ),
        )
    )
    assert codes(findings) == ["duplicate-text-across-products"]
    assert findings[0].severity == ERROR


def test_identical_text_within_one_product_is_a_warning_not_an_error():
    findings = validation.check_duplicate_text(
        dataset_of(example(), example(example_id="p001_02/ocr", image_sha256=DIGEST_B))
    )
    assert codes(findings) == ["duplicate-text-within-product"]
    assert findings[0].severity == WARNING


def test_duplicate_detection_ignores_whitespace_and_case():
    findings = validation.check_duplicate_text(
        dataset_of(
            example(),
            example(
                example_id="p002_01/ocr",
                product_id="product_002",
                image_sha256=DIGEST_B,
                text="INGREDIENTS   WHEAT\nFLOUR\tSUGAR  SALT",
            ),
        )
    )
    assert codes(findings) == ["duplicate-text-across-products"]


def test_empty_readings_are_not_duplicates_of_each_other():
    """A front panel OCR read as nothing is a real outcome the seed set keeps."""
    findings = validation.check_duplicate_text(
        dataset_of(
            example(text=""),
            example(example_id="p002_01/ocr", product_id="product_002",
                    image_sha256=DIGEST_B, text="   \n  "),
        )
    )
    assert findings == []


# --- 9: product-level split integrity ----------------------------------------


def test_a_product_in_two_folds_is_leakage():
    findings = validation.check_fold_integrity(
        {"train": ["product_001", "product_002"], "test": ["product_001"]}
    )
    assert codes(findings) == ["product-leakage"]
    assert findings[0].subjects == ("product_001",)


def test_a_clean_split_is_silent():
    assert (
        validation.check_fold_integrity(
            {"train": ["product_001", "product_002"], "test": ["product_003"]}
        )
        == []
    )


def test_leave_one_product_out_folds_hold_out_exactly_one_product_each(seed):
    folds = validation.leave_one_product_out_folds(seed)
    assert len(folds) == len(seed.product_ids)
    assert all(len(products) == 1 for products in folds.values())
    assert validation.check_fold_integrity(folds) == []


def test_no_seed_product_straddles_a_training_split(seed):
    """The regression test for the property every reported figure rests on.

    Rebuilds each fold the way `train.cross_validate` does and checks the two
    halves against each other. Deliberately free of scikit-learn: the other
    copy of this check lives behind an `importorskip`, so on a machine with no
    training extra installed it silently does not run - which is exactly the
    machine where a grouping change would go unnoticed.
    """
    groups = seed.by_product()
    assert len(groups) == 10

    for held_out in groups:
        training_products = sorted(set(groups) - {held_out})
        findings = validation.check_fold_integrity(
            {"train": training_products, "holdout": [held_out]}
        )
        assert findings == [], held_out
        assert held_out not in training_products


def test_the_leakage_check_catches_a_product_put_on_both_sides(seed):
    """The same construction, deliberately broken, so the test above can fail."""
    held_out = seed.product_ids[0]
    findings = validation.check_fold_integrity(
        {"train": list(seed.product_ids), "holdout": [held_out]}
    )
    assert codes(findings) == ["product-leakage"]
    assert findings[0].subjects == (held_out,)


def test_every_text_of_one_product_moves_together(seed):
    """Five seed products carry both OCR and a transcription of one photograph.

    Grouping is by `product_id`, so they share a fold by construction - which
    is the point: training on a transcription and testing on the OCR of the
    same panel is the most flattering leakage there is.
    """
    doubled = {
        product: examples
        for product, examples in seed.by_product().items()
        if {example.text_source for example in examples}
        == {"ocr", "manual_transcription"}
    }
    assert len(doubled) == 5
    folds = validation.leave_one_product_out_folds(seed)
    for product in doubled:
        holding = [name for name, products in folds.items() if product in products]
        assert len(holding) == 1, product


# --- 10: coverage -------------------------------------------------------------


def test_a_class_with_no_example_is_reported_as_empty():
    findings = validation.check_class_coverage(dataset_of(example()))
    empty = [f for f in findings if f.code == "empty-class"]
    assert "medical-device" in {f.subjects[0] for f in empty}


def test_a_class_with_one_product_cannot_be_measured_and_says_so():
    findings = validation.check_class_coverage(dataset_of(example()))
    single = [f for f in findings if f.code == "single-product-class"]
    assert single and single[0].subjects == ("general-food",)


def test_two_products_clear_the_single_product_warning():
    data = dataset_of(
        example(),
        example(example_id="p002_01/ocr", product_id="product_002",
                image_sha256=DIGEST_B, text="rice flour salt"),
    )
    findings = validation.check_class_coverage(data)
    assert "general-food" not in {
        f.subjects[0] for f in findings if f.code == "single-product-class"
    }


# --- 7: verification ----------------------------------------------------------


def test_unverified_labels_are_a_warning_by_default():
    findings = validation.check_verification(dataset_of(example()))
    assert codes(findings, WARNING) == ["unverified-labels"]
    assert codes(findings, ERROR) == []


def test_require_verified_promotes_it_to_an_error():
    findings = validation.check_verification(
        dataset_of(example()), require_verified=True
    )
    assert codes(findings, ERROR) == ["unverified-labels"]


def test_a_verified_label_raises_nothing():
    data = dataset_of(
        example(
            label_verified_by="A Person",
            label_verified_on="2026-09-23",
            label_verification_ref="s1",
        )
    )
    assert validation.check_verification(data) == []


# --- the whole battery, and how it refuses -----------------------------------


def test_raise_for_errors_carries_every_error_not_just_the_first():
    data = dataset_of(
        example(),
        example(example_id="dupe/ocr", product_id="product_999"),
    )
    with pytest.raises(DatasetIntegrityError) as caught:
        validation.raise_for_errors(validation.validate(data))
    assert len(caught.value.findings) >= 2
    assert "duplicate-product" in str(caught.value)


def test_the_integrity_error_is_a_classification_data_error():
    """So a caller that already handles dataset failure handles this one."""
    assert issubclass(DatasetIntegrityError, ClassificationDataError)


def test_validate_reports_errors_before_warnings():
    data = dataset_of(example(), example(example_id="dupe/ocr", product_id="product_999"))
    severities = [finding.severity for finding in validation.validate(data)]
    assert severities == sorted(severities, key=lambda s: {ERROR: 0, WARNING: 1}[s])


# --- the shipped seed set ------------------------------------------------------


def test_the_seed_set_has_no_integrity_errors(seed):
    """It is thin, not broken. Every finding against it is a warning."""
    findings = validation.validate(seed)
    assert validation.errors(findings) == ()


def test_the_seed_set_reports_exactly_the_gaps_the_docs_name(seed):
    findings = validation.validate(seed)
    empty = {f.subjects[0] for f in findings if f.code == "empty-class"}
    single = {f.subjects[0] for f in findings if f.code == "single-product-class"}
    assert empty == {
        "alcoholic-beverage",
        "medical-device",
        "tobacco-product",
        "electronic-product",
        "other-non-food",
    }
    assert single == {
        "health-supplement",
        "cosmetics-and-toiletries",
        "cleaning-product",
    }


def test_the_seed_set_is_entirely_unverified_and_the_check_says_so(seed):
    findings = validation.validate(seed)
    unverified = [f for f in findings if f.code == "unverified-labels"]
    assert len(unverified) == 1
    assert "33 of 33" in unverified[0].message


def test_the_seed_set_fails_under_require_verified(seed):
    """The switch a future held-out set is validated under. This set is not it."""
    findings = validation.validate(seed, require_verified=True)
    assert codes(validation.errors(findings)) == ["unverified-labels"]


# --- the coverage report -------------------------------------------------------


def test_coverage_has_a_row_for_every_subcategory_including_empty_ones(seed):
    rows = validation.coverage(seed)
    assert [row.subcategory for row in rows] == [
        item.code for item in taxonomy.SUBCATEGORIES
    ]


def test_coverage_totals_match_the_dataset(seed):
    rows = validation.coverage(seed)
    assert sum(row.examples for row in rows) == len(seed.examples)
    assert sum(row.verified for row in rows) == 0
    assert sum(row.unverified for row in rows) == 33


def test_the_formatted_table_states_the_totals(seed):
    text = validation.format_coverage(seed)
    assert "Products:   10" in text
    assert "Examples:   33" in text
    assert "Images:     28" in text
    assert "Verified:   0" in text


# --- the command ---------------------------------------------------------------


def test_the_command_exits_zero_on_the_seed_set(capsys):
    assert validation.main([]) == 0
    assert "DATASET TOTALS" in capsys.readouterr().out


def test_the_command_exits_one_under_require_verified(capsys):
    assert validation.main(["--require-verified"]) == 1


def test_the_command_refuses_a_broken_dataset(tmp_path, capsys):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert validation.main(["--dataset", str(broken)]) == 1
    assert "could not be loaded" in capsys.readouterr().err


def test_the_command_fails_on_a_dataset_with_an_integrity_error(tmp_path, capsys):
    document = json.loads(load_dataset().path.read_text(encoding="utf-8"))
    twin = copy.deepcopy(document["examples"][0])
    twin["example_id"] = "imported-twice/ocr"
    twin["product_id"] = "product_999"
    document["examples"].append(twin)
    path = tmp_path / "duped.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert validation.main(["--dataset", str(path), "--no-ledger"]) == 1
    assert "duplicate-product" in capsys.readouterr().out
