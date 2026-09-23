"""The human-verification ledger: what it refuses, and what applying it does.

The property these tests exist to protect is one sentence: **a label becomes
verified only when a person says so, and only with a record of what they
looked at.** Everything else here is a way that could quietly stop being true
- a model name in the verifier field, a date with no ledger entry behind it, a
decision applied to a dataset version it was not made about, an `unresolved`
outcome treated as a decision.

The shipped ledger is empty, and a test asserts that too. An empty ledger is
the honest state of a dataset nobody has verified; a test that required at
least one entry would be pressure to write one.
"""

from __future__ import annotations

import copy
import json

import pytest

from labelextract.classification import verification
from labelextract.classification.dataset import (
    ClassificationDataError,
    load_dataset,
    parse_dataset,
    seed_dataset_path,
)
from labelextract.classification.validation import ERROR, WARNING

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.fixture
def seed():
    return load_dataset()


def example(**overrides):
    row = {
        "example_id": "p001_01/ocr",
        "product_id": "product_001",
        "category": "packaged-non-food",
        "subcategory": "cleaning-product",
        "text": "aerosol foam cleaner flammable",
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
        "note": "back panel",
    }
    row.update(overrides)
    return row


def document(*examples):
    return {
        "dataset_version": "t",
        "created_on": "2026-01-01",
        "description": "test",
        "taxonomy_version": "1",
        "examples": list(examples) or [example()],
    }


def entry(**overrides):
    row = {
        "ref": "s1",
        "product_id": "product_001",
        "verifier": "A Person",
        "verified_on": "2026-09-23",
        "product_identity": "ShineXPro helmet cleaner, 120 g aerosol",
        "category": "packaged-non-food",
        "subcategory": "cleaning-product",
        "outcome": "confirmed",
        "example_ids": ["p001_01/ocr"],
        "image_sha256": [DIGEST_A],
        "note": "",
    }
    row.update(overrides)
    return row


def ledger(*entries, dataset_version="t"):
    return verification.parse_ledger(
        {
            "ledger_version": verification.LEDGER_VERSION,
            "dataset_version": dataset_version,
            "description": "test ledger",
            "entries": list(entries),
        }
    )


def codes(findings, severity=None):
    return sorted(
        f.code for f in findings if severity is None or f.severity == severity
    )


# --- a machine may never verify a label ---------------------------------------


@pytest.mark.parametrize(
    "verifier",
    [
        "claude-opus-5",
        "claude-opus-5-draft",
        "tfidf-logreg 0.1.0",
        "the classifier",
        "GPT-4",
        "automated review",
        "review-bot",
        "verify_labels.py script",
    ],
)
def test_a_machine_cannot_be_a_verifier(verifier):
    """The single rule this whole module exists to enforce."""
    with pytest.raises(ClassificationDataError, match="looks like a machine"):
        ledger(entry(verifier=verifier))


def test_the_classifier_being_trained_is_refused_by_name():
    with pytest.raises(ClassificationDataError, match="own training data"):
        ledger(entry(verifier="tfidf-logreg"))


def test_a_person_is_accepted():
    assert ledger(entry()).entries[0].verifier == "A Person"


def test_the_dataset_loader_refuses_a_machine_in_label_verified_by():
    """The same rule, enforced on the other side - a hand-edited dataset."""
    with pytest.raises(ClassificationDataError, match="must be a person"):
        parse_dataset(
            document(
                example(
                    label_verified_by="claude-opus-5",
                    label_verified_on="2026-09-23",
                    label_verification_ref="s1",
                )
            )
        )


# --- verification provenance is all-or-none -----------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"label_verified_by": "A Person"},
        {"label_verified_by": "A Person", "label_verified_on": "2026-09-23"},
        {"label_verified_by": "A Person", "label_verification_ref": "s1"},
        {"label_verified_on": "2026-09-23"},
        {"label_verification_ref": "s1"},
    ],
)
def test_a_partial_verification_is_refused(fields):
    """A name with no date and no record is not provenance, and must not count."""
    with pytest.raises(ClassificationDataError, match="all-or-none"):
        parse_dataset(document(example(**fields)))


def test_a_complete_verification_parses():
    data = parse_dataset(
        document(
            example(
                label_verified_by="A Person",
                label_verified_on="2026-09-23",
                label_verification_ref="s1",
            )
        )
    )
    assert data.examples[0].is_verified
    assert data.examples[0].label_verified_on == "2026-09-23"
    assert data.examples[0].label_verification_ref == "s1"


@pytest.mark.parametrize("bad", ["23-09-2026", "2026-9-23", "2026/09/23", "yesterday"])
def test_a_verification_date_must_be_an_iso_date(bad):
    with pytest.raises(ClassificationDataError, match="ISO YYYY-MM-DD"):
        parse_dataset(
            document(
                example(
                    label_verified_by="A Person",
                    label_verified_on=bad,
                    label_verification_ref="s1",
                )
            )
        )


def test_all_three_null_is_the_normal_unverified_case():
    data = parse_dataset(document(example()))
    assert not data.examples[0].is_verified


# --- the ledger format --------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda e: e.update(outcome="probably"), "outcome must be one of"),
        (lambda e: e.update(category="packaged-thing"), "not a taxonomy category"),
        (lambda e: e.update(subcategory="nope"), "not a taxonomy subcategory"),
        (lambda e: e.update(subcategory="general-food"), "does not belong"),
        (lambda e: e.update(product_identity=""), "product_identity"),
        (lambda e: e.update(example_ids=[]), "example_ids"),
        (lambda e: e.update(image_sha256=[]), "image_sha256"),
        (lambda e: e.update(verified_on="2026-13-01"), "ISO YYYY-MM-DD"),
        (lambda e: e.pop("verifier"), "verifier"),
    ],
)
def test_a_malformed_entry_is_refused(mutate, message):
    row = entry()
    mutate(row)
    with pytest.raises(ClassificationDataError, match=message):
        ledger(row)


def test_an_entry_must_say_what_the_product_actually_is():
    """Confirming a code without naming the package records an opinion."""
    with pytest.raises(ClassificationDataError, match="product_identity"):
        ledger(entry(product_identity="   "))


def test_duplicate_refs_are_refused():
    with pytest.raises(ClassificationDataError, match="duplicate ledger ref"):
        ledger(entry(), entry(product_id="product_002"))


def test_a_ledger_speaking_another_version_is_refused():
    with pytest.raises(ClassificationDataError, match="this code speaks"):
        verification.parse_ledger(
            {
                "ledger_version": "something-else",
                "dataset_version": "t",
                "description": "x",
                "entries": [],
            }
        )


def test_an_empty_ledger_is_valid():
    """The honest state of a dataset nobody has verified yet."""
    assert ledger().entries == ()


# --- outcomes -----------------------------------------------------------------


def test_confirmed_and_changed_are_applicable():
    assert ledger(entry(outcome="confirmed")).applicable()
    assert ledger(entry(outcome="changed")).applicable()


def test_unresolved_is_recorded_but_never_applied():
    """A person who looked and did not decide has not verified anything."""
    book = ledger(entry(outcome="unresolved"))
    assert book.entries and book.applicable() == ()
    assert book.covered_example_ids() == frozenset()

    result = verification.apply(document(), book)
    assert result["examples"][0]["label_verified_by"] is None
    assert result["dataset_version"] == "t"


# --- applying -----------------------------------------------------------------


def test_applying_a_confirmation_stamps_all_three_fields():
    result = verification.apply(
        document(), ledger(entry()), dataset_version="t-v2"
    )
    row = result["examples"][0]
    assert row["label_verified_by"] == "A Person"
    assert row["label_verified_on"] == "2026-09-23"
    assert row["label_verification_ref"] == "s1"
    assert parse_dataset(result).examples[0].is_verified


def test_applying_a_change_relabels_and_verifies_together():
    """The correction and the verification land in one step, never separately."""
    result = verification.apply(
        document(),
        ledger(
            entry(
                outcome="changed",
                category="packaged-non-food",
                subcategory="cosmetics-and-toiletries",
            )
        ),
        dataset_version="t-v2",
    )
    row = result["examples"][0]
    assert row["subcategory"] == "cosmetics-and-toiletries"
    assert row["label_verified_by"] == "A Person"


def test_applying_requires_a_new_dataset_version():
    """The digest changes; a version already trained against may not be edited."""
    with pytest.raises(ClassificationDataError, match="new dataset_version"):
        verification.apply(document(), ledger(entry()))


def test_applying_refuses_to_reuse_the_same_version():
    with pytest.raises(ClassificationDataError, match="publish a new one"):
        verification.apply(document(), ledger(entry()), dataset_version="t")


def test_applying_nothing_needs_no_new_version():
    result = verification.apply(document(), ledger())
    assert result["dataset_version"] == "t"


def test_apply_does_not_mutate_the_document_it_was_given():
    original = document()
    snapshot = copy.deepcopy(original)
    verification.apply(original, ledger(entry()), dataset_version="t-v2")
    assert original == snapshot


def test_created_on_defaults_to_the_latest_verification_date():
    """Deterministic: the result does not depend on when the command ran."""
    result = verification.apply(
        document(example(), example(example_id="p002/ocr", product_id="product_002",
                                    image_sha256=DIGEST_B)),
        ledger(
            entry(verified_on="2026-09-20"),
            entry(ref="s2", product_id="product_002", verified_on="2026-09-23",
                  example_ids=["p002/ocr"], image_sha256=[DIGEST_B]),
        ),
        dataset_version="t-v2",
    )
    assert result["created_on"] == "2026-09-23"


def test_applying_an_entry_for_an_unknown_example_refuses():
    with pytest.raises(ClassificationDataError, match="not in the document"):
        verification.apply(
            document(), ledger(entry(example_ids=["nope/ocr"])), dataset_version="t-v2"
        )


def test_applying_an_entry_whose_example_belongs_to_another_product_refuses():
    with pytest.raises(ClassificationDataError, match="belongs to"):
        verification.apply(
            document(),
            ledger(entry(product_id="product_002")),
            dataset_version="t-v2",
        )


# --- reconciling a ledger against a dataset ------------------------------------


def test_a_verified_row_with_no_ledger_entry_is_an_error():
    """Somebody typed a name into a field."""
    data = parse_dataset(
        document(
            example(
                label_verified_by="A Person",
                label_verified_on="2026-09-23",
                label_verification_ref="s1",
            )
        )
    )
    findings = verification.reconcile(data, ledger())
    assert "verified-without-ledger-entry" in codes(findings, ERROR)


def test_a_verified_row_citing_an_unknown_ref_is_an_error():
    data = parse_dataset(
        document(
            example(
                label_verified_by="A Person",
                label_verified_on="2026-09-23",
                label_verification_ref="s99",
            )
        )
    )
    findings = verification.reconcile(data, ledger(entry()))
    assert "unknown-verification-ref" in codes(findings, ERROR)


def test_a_ledger_that_disagrees_with_the_dataset_label_is_an_error():
    data = parse_dataset(document(example(subcategory="cosmetics-and-toiletries")))
    findings = verification.reconcile(data, ledger(entry()))
    assert "ledger-label-disagreement" in codes(findings, ERROR)


def test_a_ledger_entry_for_an_unknown_product_is_an_error():
    data = parse_dataset(document())
    findings = verification.reconcile(data, ledger(entry(product_id="product_404")))
    assert "ledger-unknown-product" in codes(findings, ERROR)


def test_a_ledger_entry_for_an_unknown_example_is_an_error():
    data = parse_dataset(document())
    findings = verification.reconcile(
        data, ledger(entry(example_ids=["p001_01/ocr", "ghost/ocr"]))
    )
    assert "ledger-unknown-example" in codes(findings, ERROR)


def test_a_ledger_written_against_another_dataset_version_is_an_error():
    """A decision about one version is not automatically true of another."""
    data = parse_dataset(document())
    findings = verification.reconcile(data, ledger(entry(), dataset_version="other"))
    assert "ledger-dataset-mismatch" in codes(findings, ERROR)


def test_an_empty_ledger_never_mismatches_a_version():
    data = parse_dataset(document())
    assert verification.reconcile(data, ledger(dataset_version="other")) == []


def test_a_decided_entry_not_yet_applied_is_a_warning():
    data = parse_dataset(document())
    findings = verification.reconcile(data, ledger(entry()))
    assert codes(findings, WARNING) == ["ledger-entry-not-applied"]


def test_an_applied_ledger_reconciles_clean():
    """Apply, publish under the new version, and the two agree with no findings."""
    applied = verification.apply(document(), ledger(entry()), dataset_version="t-v2")
    data = parse_dataset(applied)
    assert verification.reconcile(data, ledger(entry(), dataset_version="t-v2")) == []


def test_a_cited_photograph_the_dataset_does_not_know_is_a_warning():
    data = parse_dataset(document())
    findings = verification.reconcile(
        data, ledger(entry(image_sha256=[DIGEST_A, DIGEST_B]))
    )
    assert "ledger-unknown-image" in codes(findings, WARNING)


# --- worksheets ----------------------------------------------------------------


def test_a_template_fills_in_only_what_the_dataset_knows(seed):
    template = verification.entry_template(seed, "product_001", ref="s13")
    assert template["product_id"] == "product_001"
    assert len(template["example_ids"]) == 7
    assert len(template["image_sha256"]) == 6
    for blank in ("verifier", "verified_on", "product_identity", "category",
                  "subcategory", "outcome"):
        assert template[blank] == "", blank


def test_a_template_labels_the_drafted_category_as_not_a_suggestion(seed):
    """Pre-filling it is how a draft becomes a verification with nobody deciding."""
    template = verification.entry_template(seed, "product_001", ref="s13")
    assert "NOT a suggestion" in template["note"]
    assert template["category"] == ""


def test_a_template_for_an_unknown_product_refuses(seed):
    with pytest.raises(ClassificationDataError, match="no such product"):
        verification.entry_template(seed, "product_404", ref="s1")


def test_there_is_a_template_for_every_product(seed):
    assert len(verification.entry_templates(seed)) == len(seed.product_ids)


def test_a_blank_template_is_not_a_valid_entry(seed):
    """It is a worksheet. It only becomes a record once a person fills it in."""
    with pytest.raises(ClassificationDataError):
        ledger(verification.entry_template(seed, "product_001", ref="s13"))


# --- the shipped ledger --------------------------------------------------------


def test_the_shipped_ledger_loads():
    book = verification.load_ledger()
    assert book.ledger_version == verification.LEDGER_VERSION
    assert book.path == verification.ledger_path()


def test_the_shipped_ledger_is_empty_because_nothing_has_been_verified():
    """Not an oversight, and not something to fix by writing an entry."""
    assert verification.load_ledger().entries == ()


def test_the_shipped_ledger_is_written_against_the_shipped_dataset(seed):
    assert verification.load_ledger().dataset_version == seed.dataset_version


def test_the_shipped_ledger_and_dataset_reconcile_clean(seed):
    assert verification.reconcile(seed, verification.load_ledger()) == []


def test_the_summary_reports_the_seed_set_as_wholly_unverified(seed):
    summary = verification.verification_summary(seed, verification.load_ledger())
    assert summary["verified_examples"] == 0
    assert summary["unverified_examples"] == 33
    assert summary["verified_products"] == 0
    assert summary["unverified_products"] == 10
    assert summary["ledger_entries"] == 0
    assert summary["verifiers"] == []


def test_applying_the_shipped_ledger_leaves_the_seed_set_byte_identical():
    """Nothing to apply, so nothing changes - including the digest."""
    original = json.loads(seed_dataset_path().read_text(encoding="utf-8"))
    result = verification.apply(original, verification.load_ledger())
    assert result == original


def test_a_new_ledger_starts_empty():
    fresh = verification.new_ledger_document("product-classification-v0.2", "x")
    assert fresh["entries"] == []
    assert verification.parse_ledger(fresh).entries == ()
