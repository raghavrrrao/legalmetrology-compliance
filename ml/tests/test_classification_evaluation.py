"""Whether the evaluation is honest enough to decide anything with.

The classifier's own accuracy is not the question this suite asks. The
question is whether a person reading the committed metrics report can tell
**a model that learned to read a label from one that learned the class
balance**, and whether the report contains the evidence an acceptance policy
would have to rest on. Three properties, each with a test that fails loudly
if the evaluation stops answering them:

1. **No leakage.** A product's photographs are one unit. If any example of a
   held-out product were in its own training fold the whole report would be
   measuring memorisation, and every number in it would be meaningless.
2. **A floor to compare against.** A constant answer scores the majority
   class's share - on a set that is two-thirds food, 0.64 strict accuracy
   from a function with no features at all. A cross-validated score below
   that is not a weak model; it is no model.
3. **Confidence that means something, or is known not to.** An acceptance
   policy is a claim that above some confidence the answer can be trusted.
   That claim is only available if accuracy rises with confidence.

The last two are the reason `AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS`
is empty, and the tripwires at the bottom fail if that ever stops being the
honest reading of the shipped report - including if it improves, which is
when the policy should be re-examined rather than left alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from labelextract.classification import taxonomy
from labelextract.classification.classifier import ClassifierConfig, shipped_artifact_path
from labelextract.classification.dataset import load_dataset
from labelextract.classification.train import (
    THRESHOLD_SWEEP,
    TrainingConfig,
    confidence_separation,
    cross_validate,
    per_product,
    threshold_sweep,
    trivial_baselines,
)

sklearn = pytest.importorskip(
    "sklearn", reason="training-only analyses; install the [classify-train] extra"
)


@pytest.fixture(scope="module")
def seed():
    return load_dataset()


@pytest.fixture(scope="module")
def report() -> dict:
    """The committed metrics report for the shipped artifact."""
    path = shipped_artifact_path().with_suffix(".metrics.json")
    return json.loads(path.read_text(encoding="utf-8"))


# --- 1. no product may appear on both sides of a fold -------------------------


def test_no_example_of_a_held_out_product_is_in_its_own_training_fold(seed):
    """The property every number in the report depends on.

    Checked against the real seed set rather than a fixture, and by
    reconstructing each fold's training set the way `cross_validate` does -
    so a change to the grouping that reintroduced leakage fails here.
    """
    groups = seed.by_product()
    assert len(groups) == 10, "the seed set is ten products"

    for held_out, held_examples in groups.items():
        training = [
            example
            for product, examples in groups.items()
            if product != held_out
            for example in examples
        ]
        training_ids = {example.example_id for example in training}
        training_products = {example.product_id for example in training}

        assert held_out not in training_products
        for example in held_examples:
            assert example.example_id not in training_ids
        # Every other product is present: holding one out must not drop others.
        assert training_products == set(groups) - {held_out}


def test_a_products_transcription_and_its_ocr_never_straddle_a_fold(seed):
    """Five products carry both a manual transcription and OCR of the same
    photograph. They are near-duplicate texts of one physical package, so a
    split that separated them would train on a transcription and test on the
    OCR of the same label - the most flattering kind of leakage there is."""
    by_product = seed.by_product()
    doubled = {
        product: examples
        for product, examples in by_product.items()
        if {example.text_source for example in examples} == {"ocr", "manual_transcription"}
    }
    assert doubled, "the seed set has products with both sources"

    for product, examples in doubled.items():
        # Grouping is by product_id, so both sources share a fold by
        # construction. Asserted rather than assumed.
        assert len({example.product_id for example in examples}) == 1
        assert {example.product_id for example in examples} == {product}


def test_every_example_reaches_exactly_one_held_out_fold(seed):
    predictions, notes = cross_validate(seed, TrainingConfig(), ClassifierConfig())

    assert notes["method"] == "leave-one-product-out"
    assert len(predictions) == len(seed.examples)
    seen = [p.example_id for p in predictions]
    assert len(seen) == len(set(seen)), "an example was scored twice"
    assert set(seen) == {example.example_id for example in seed.examples}


# --- 2. the floor a model has to clear ----------------------------------------


def test_trivial_baselines_score_what_the_class_balance_says(seed):
    baselines = trivial_baselines(seed)

    assert set(baselines) == {
        "always-packaged-food",
        "always-packaged-non-food",
        "always-unknown",
    }
    # 21 of 33 examples are food, so a constant "food" scores 21/33.
    assert baselines["always-packaged-food"]["strict_accuracy"] == pytest.approx(21 / 33, abs=1e-4)
    assert baselines["always-packaged-non-food"]["strict_accuracy"] == pytest.approx(12 / 33, abs=1e-4)
    # Abstaining always is never "accurate", and never wrong either.
    assert baselines["always-unknown"]["strict_accuracy"] == 0.0
    assert baselines["always-unknown"]["unknown_rate"] == 1.0


def test_the_report_carries_its_own_comparison(report):
    """A report without the floor in it invites the headline to be read alone."""
    cv = report["cross_validation"]

    assert "trivial_baselines" in cv
    assert "threshold_sweep" in cv
    assert "confidence_separation" in cv
    assert "per_product" in cv
    assert len(cv["per_product"]) == report["dataset"]["n_products"]


# --- 3. whether confidence is evidence of anything ----------------------------


def test_threshold_sweep_counts_only_committed_predictions(seed):
    predictions, _ = cross_validate(seed, TrainingConfig(), ClassifierConfig())
    rows = threshold_sweep(predictions)

    assert [row["min_confidence"] for row in rows] == list(THRESHOLD_SWEEP)
    committed = [
        p for p in predictions
        if p.category not in (None, taxonomy.UNKNOWN) and p.confidence is not None
    ]
    assert rows[0]["n_committed"] == len(
        [p for p in committed if p.confidence >= rows[0]["min_confidence"]]
    )
    for row in rows:
        assert row["n_correct"] <= row["n_committed"]
        assert 0.0 <= row["coverage"] <= 1.0
        # Raising the bar can only ever keep fewer predictions.
        assert row["n_committed"] <= rows[0]["n_committed"]


def test_confidence_separation_reports_the_overlap_rather_than_hiding_it(seed):
    predictions, _ = cross_validate(seed, TrainingConfig(), ClassifierConfig())

    separation = confidence_separation(predictions)

    assert separation["correct"]["n"] + separation["wrong"]["n"] == len(
        [p for p in predictions if p.category not in (None, taxonomy.UNKNOWN)]
    )
    # `separable` is true only when every right answer outranks every wrong
    # one. On this artifact it does not - see the tripwire below.
    assert separation["separable"] is (
        separation["correct"]["min"] is not None
        and separation["wrong"]["max"] is not None
        and separation["correct"]["min"] > separation["wrong"]["max"]
    )


def test_per_product_accounts_for_every_example(seed):
    predictions, _ = cross_validate(seed, TrainingConfig(), ClassifierConfig())

    rows = per_product(predictions)

    assert len(rows) == len(seed.product_ids)
    assert sum(row["n_examples"] for row in rows) == len(seed.examples)
    for row in rows:
        assert row["n_correct"] + row["n_unknown"] <= row["n_examples"]
        assert row["true_category"] in taxonomy.CATEGORIES


# --- the tripwires ------------------------------------------------------------
#
# These pin the *reading* of the shipped report that the empty acceptance
# policy rests on. They are written to fail if the situation improves, which
# is deliberate: an improvement is exactly when somebody should revisit
# `AUTOMATIC_APPLICABILITY_ACCEPTED_CLASSIFIERS` and the documentation around
# it, rather than discover months later that the evidence moved.


def test_the_shipped_model_does_not_beat_a_classifier_with_no_features(report):
    """If this fails, the classifier has started reading the label.

    Re-run the evaluation, update docs/ml/product-classification.md and
    docs/automatic-applicability.md, and only then consider whether an
    acceptance policy entry is defensible. Do not simply delete this test.
    """
    cv = report["cross_validation"]
    model_f1 = cv["metrics"]["category"]["macro_f1"]
    best_trivial = max(
        row["macro_f1"] for row in cv["trivial_baselines"].values()
    )

    assert model_f1 <= best_trivial, (
        f"The shipped model's macro-F1 ({model_f1}) now exceeds the best "
        f"trivial baseline ({best_trivial}). This is good news and it "
        f"invalidates the documented justification for the empty automatic-"
        f"applicability policy. Re-read docs/automatic-applicability.md."
    )


def test_no_confidence_threshold_makes_the_shipped_model_reliable(report):
    """The evidence an acceptance policy would need, and does not have.

    On the shipped artifact accuracy *falls* as the confidence bar rises -
    every prediction above 0.75 is wrong - so no cut can be chosen from it.
    """
    sweep = report["cross_validation"]["threshold_sweep"]
    measured = [row for row in sweep if row["accuracy_on_predicted"] is not None]
    assert measured, "the sweep reported nothing to read"

    best = max(row["accuracy_on_predicted"] for row in measured)
    assert best < 0.9, (
        f"Accuracy on committed predictions reached {best} at some confidence "
        f"threshold. If that holds with usable coverage, an acceptance policy "
        f"may now be arguable - see docs/automatic-applicability.md before "
        f"changing the setting."
    )
    assert report["cross_validation"]["confidence_separation"]["separable"] is False


def test_the_report_describes_the_committed_dataset(report, seed):
    """Provenance: a report about some other dataset cannot justify anything."""
    assert report["dataset"]["sha256"] == seed.sha256
    assert report["dataset"]["n_examples"] == len(seed.examples)
    assert report["dataset"]["n_products"] == len(seed.product_ids)
    assert report["dataset"]["unverified_labels"] == len(seed.examples), (
        "every seed label is still model-drafted and unverified"
    )
