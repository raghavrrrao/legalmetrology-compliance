"""Scoring: the outcome table, and the numbers it refuses to produce.

Each test drives one cell of the table in `metrics.py` with a known prediction
against a known annotation and asserts the counts that result. The arithmetic
is trivial by design - the value of these tests is that they pin *which cell a
situation falls into*, which is the part that is easy to get subtly wrong and
impossible to notice afterwards.

Two properties get the most coverage, because they are the ones a wrong
implementation would flatter:

- a **fabricated** value - a reading produced for a declaration a person could
  not read - is a false positive and is counted as such;
- an **un-annotated** field is excluded, never counted as a negative.
"""

from __future__ import annotations

import pytest

from labelextract.contracts import LabelFieldKey
from labelextract.evaluation import (
    FieldTruthState,
    SampleAnnotation,
    SamplePrediction,
    normalise_for_comparison,
    score,
)
from labelextract.evaluation.metrics import levenshtein
from labelextract.evaluation.prediction import FieldPrediction
from labelextract.fields import SUPPORTED_KEYS

QUANTITY = LabelFieldKey.NET_QUANTITY


def truth(state: str, value: str | None = None, key: str = "net_quantity") -> SampleAnnotation:
    field = {"key": key, "state": state}
    if value is not None:
        field["value"] = value
    return SampleAnnotation.from_dict(
        {
            "sample_id": "eval_0001",
            "annotated_by": "a-reviewer",
            "annotated_on": "2026-01-15",
            "fields": [field],
        }
    )


def predicted(
    normalized: dict | None,
    *,
    raw: str = "Net Qty: 500 g",
    key: LabelFieldKey = QUANTITY,
    unread: set[LabelFieldKey] | None = None,
    text: str = "",
) -> SamplePrediction:
    fields = ()
    if normalized is not None:
        fields = (FieldPrediction(key=key, raw_value=raw, normalized_value=normalized),)
    return SamplePrediction(
        sample_id="eval_0001",
        status="completed",
        engine_name="stub",
        engine_version="0.0.0",
        recognised_text=text,
        fields=fields,
        unread_keys=frozenset(unread or set()),
    )


def nothing_predicted(**kwargs) -> SamplePrediction:
    return predicted(None, **kwargs)


def counts_for(annotation, prediction, key: LabelFieldKey = QUANTITY):
    return score([(annotation, prediction)]).per_field[key]


# --- PRESENT_AND_READABLE ----------------------------------------------------


def test_a_correct_reading_is_a_true_positive_with_the_right_value():
    counts = counts_for(
        truth("present_and_readable", "500 g"),
        predicted({"base_quantity": 500, "base_unit": "g", "uncertain": False}),
    )
    assert (counts.true_positive, counts.false_positive, counts.false_negative) == (1, 0, 0)
    assert (counts.value_correct, counts.value_incorrect) == (1, 0)
    assert counts.precision == 1.0
    assert counts.recall == 1.0
    assert counts.f1 == 1.0
    assert counts.value_accuracy == 1.0


def test_a_detected_declaration_with_the_wrong_value_is_still_detected():
    """Detection and value accuracy are different questions, reported separately."""
    counts = counts_for(
        truth("present_and_readable", "500 g"),
        predicted({"base_quantity": 250, "base_unit": "g"}, raw="Net Qty: 250 g"),
    )
    assert counts.true_positive == 1
    assert (counts.value_correct, counts.value_incorrect) == (0, 1)
    assert counts.recall == 1.0
    assert counts.value_accuracy == 0.0


def test_a_missed_readable_declaration_is_a_false_negative():
    counts = counts_for(truth("present_and_readable", "500 g"), nothing_predicted())
    assert counts.false_negative == 1
    assert counts.recall == 0.0


def test_a_withheld_value_does_not_count_as_a_detection():
    """The extractor refusing to guess is not the same as it finding the value.

    Scoring a withheld reading as a detection would reward exactly the guessing
    the extractor is built to avoid.
    """
    counts = counts_for(
        truth("present_and_readable", "500 g"),
        predicted({"uncertain": True, "candidates": ["500 g", "50 g"]}),
    )
    assert counts.true_positive == 0
    assert counts.false_negative == 1


# --- PRESENT_BUT_UNREADABLE: the fabrication cell ---------------------------


def test_a_value_for_an_unreadable_declaration_is_a_fabrication():
    """The failure this whole architecture exists to prevent."""
    counts = counts_for(
        truth("present_but_unreadable"),
        predicted({"base_quantity": 500, "base_unit": "g"}),
    )
    assert counts.fabricated == 1
    assert counts.false_positive == 1, "a fabrication is a false positive, not a category of its own"
    assert counts.true_positive == 0
    assert counts.precision == 0.0


def test_declining_to_read_an_unreadable_declaration_is_correct():
    counts = counts_for(
        truth("present_but_unreadable"), nothing_predicted(unread={QUANTITY})
    )
    assert counts.correct_unread == 1
    assert (counts.false_positive, counts.fabricated) == (0, 0)


def test_a_withheld_value_on_an_unreadable_declaration_is_also_correct():
    counts = counts_for(
        truth("present_but_unreadable"), predicted({"uncertain": True})
    )
    assert counts.correct_unread == 1
    assert counts.fabricated == 0


def test_seeing_nothing_where_a_declaration_was_unreadable_is_a_miss_not_an_error():
    counts = counts_for(truth("present_but_unreadable"), nothing_predicted())
    assert counts.missed_unread == 1
    assert (counts.false_positive, counts.false_negative) == (0, 0)


# --- NOT_PRESENT -------------------------------------------------------------


def test_a_value_for_an_absent_declaration_is_a_false_positive():
    counts = counts_for(
        truth("not_present"), predicted({"base_quantity": 500, "base_unit": "g"})
    )
    assert counts.false_positive == 1
    assert counts.fabricated == 0, "the label never named this declaration at all"


def test_naming_an_absent_declaration_is_also_a_false_positive():
    """\"The label names a net quantity\" is a claim, even with no value attached."""
    counts = counts_for(truth("not_present"), nothing_predicted(unread={QUANTITY}))
    assert counts.false_positive == 1


def test_correctly_reporting_nothing_is_a_true_negative():
    counts = counts_for(truth("not_present"), nothing_predicted())
    assert counts.true_negative == 1
    assert (counts.false_positive, counts.false_negative) == (0, 0)


# --- UNKNOWN: excluded, never a negative -------------------------------------


def test_an_unannotated_field_is_excluded_from_every_rate():
    """Otherwise precision would fall as annotation improved."""
    annotation = SampleAnnotation.from_dict(
        {
            "sample_id": "eval_0001",
            "annotated_by": "a-reviewer",
            "annotated_on": "2026-01-15",
            "fields": [],
        }
    )
    counts = counts_for(annotation, predicted({"base_quantity": 500}))

    assert counts.excluded == 1
    assert (counts.true_positive, counts.false_positive, counts.false_negative) == (0, 0, 0)
    assert counts.precision is None
    assert counts.recall is None


def test_a_rate_with_no_denominator_is_none_rather_than_zero():
    """None means "not measured". Zero is a measurement, and a damning one."""
    report = score([])
    counts = report.per_field[QUANTITY]
    assert counts.precision is None and counts.recall is None and counts.f1 is None
    assert counts.value_accuracy is None


def test_an_unsupported_key_annotation_is_counted_as_excluded():
    """The truth is worth recording before the implementation exists."""
    annotation = truth("present_and_readable", "Acme Foods, Pune", key="manufacturer_address")
    report = score([(annotation, nothing_predicted())])

    counts = report.per_field[LabelFieldKey.MANUFACTURER_ADDRESS]
    assert counts.excluded == 1
    assert counts.false_negative == 0


def test_only_supported_keys_are_scored_by_default():
    report = score([])
    assert set(report.per_field) == set(SUPPORTED_KEYS)


# --- uncertainty -------------------------------------------------------------


def test_a_confident_wrong_reading_is_a_silent_error():
    """"The last one is the number that matters." - docs/evaluation-strategy.md"""
    report = score(
        [(truth("not_present"), predicted({"base_quantity": 500, "uncertain": False}))]
    )
    uncertainty = report.uncertainty

    assert uncertainty.confident_and_wrong == 1
    assert uncertainty.confident_total == 1
    assert uncertainty.silent_error_rate == 1.0
    assert uncertainty.uncertain_rate == 0.0


def test_an_uncertain_wrong_reading_is_not_a_silent_error():
    report = score(
        [(truth("not_present"), predicted({"base_quantity": 500, "uncertain": True}))]
    )
    uncertainty = report.uncertainty

    assert uncertainty.confident_and_wrong == 0
    assert uncertainty.uncertain_and_wrong == 1
    assert uncertainty.uncertainty_precision == 1.0
    assert uncertainty.silent_error_rate is None, "no confident readings to rate"


def test_a_withheld_field_counts_toward_the_uncertain_rate():
    """Found in review: it did not, and the reported rate was actively wrong.

    A withheld reading is emitted *because* the extractor could not commit, and
    it always carries `uncertain: True`. Counting only committed readings meant
    a set where the extractor hedged on half its declarations reported
    `uncertain_rate = 0.0` - the opposite of what happened, and exactly the
    kind of flattering number this milestone exists to prevent.

    docs/evaluation-strategy.md defines the rate over "extracted fields", which
    is every field emitted.
    """
    report = score(
        [
            (
                truth("present_and_readable", "500 g"),
                predicted({"base_quantity": 500, "base_unit": "g", "uncertain": False}),
            ),
            (
                truth("present_and_readable", "500 g"),
                predicted({"uncertain": True, "candidates": ["500 g", "50 g"]}),
            ),
        ]
    )
    uncertainty = report.uncertainty

    assert uncertainty.extracted_fields == 2, "both emitted fields count"
    assert uncertainty.flagged_uncertain == 1, "the withheld field was flagged"
    assert uncertainty.uncertain_rate == 0.5
    # The other two rates deliberately count only committed readings: a
    # withheld reading asserts nothing that could be right or wrong.
    assert uncertainty.committed_readings == 1
    assert uncertainty.confident_total == 1


def test_the_three_uncertainty_rates_name_their_denominators():
    """They do not share one, so the report says which is which."""
    body = score([]).as_dict()["uncertainty"]
    assert body["denominators"] == {
        "uncertain_rate": "extracted_fields",
        "uncertainty_precision": "flagged_uncertain_committed",
        "silent_error_rate": "confident_total",
    }
    for name in body["denominators"].values():
        assert name in body, f"{name} is named as a denominator but not reported"


def test_an_uncertain_flag_on_a_correct_reading_lowers_uncertainty_precision():
    """Flagging a correct reading costs a reviewer a glance; it is still noise."""
    report = score(
        [
            (
                truth("present_and_readable", "500 g"),
                predicted({"base_quantity": 500, "base_unit": "g", "uncertain": True}),
            )
        ]
    )
    assert report.uncertainty.uncertainty_precision == 0.0


# --- CER / WER ---------------------------------------------------------------


def test_character_and_word_error_rates_need_a_transcription():
    """Unavailable, with a reason - never approximated from something cheaper."""
    report = score([(truth("present_and_readable", "500 g"), predicted({"base_quantity": 500}))])
    text = report.text.as_dict()

    assert text["cer"] is None and text["wer"] is None
    assert "cannot be computed" in text["unavailable_reason"]
    assert text["skipped_samples"] == 1


def test_a_perfect_transcription_scores_zero_error():
    annotation = SampleAnnotation.from_dict(
        {
            "sample_id": "eval_0001",
            "annotated_by": "a-reviewer",
            "annotated_on": "2026-01-15",
            "reference_text": "NET QTY 500 g",
            "fields": [],
        }
    )
    report = score([(annotation, nothing_predicted(text="NET QTY 500 g"))])

    assert report.text.cer == 0.0
    assert report.text.wer == 0.0
    assert report.text.scored_samples == 1


def test_a_known_misreading_produces_the_arithmetic_error_rate():
    """`500` read as `5OO`: two substitutions over thirteen reference characters."""
    annotation = SampleAnnotation.from_dict(
        {
            "sample_id": "eval_0001",
            "annotated_by": "a-reviewer",
            "annotated_on": "2026-01-15",
            "reference_text": "NET QTY 500 g",
            "fields": [],
        }
    )
    report = score([(annotation, nothing_predicted(text="NET QTY 5OO g"))])

    assert report.text.character_errors == 2
    assert report.text.reference_characters == 13
    assert report.text.cer == pytest.approx(2 / 13)
    # One of the four words ("NET", "QTY", "500", "g") is wrong.
    assert report.text.word_errors == 1
    assert report.text.reference_words == 4
    assert report.text.wer == pytest.approx(1 / 4)


@pytest.mark.parametrize(
    "left, right, distance",
    [("", "", 0), ("abc", "abc", 0), ("abc", "abd", 1), ("", "abc", 3), ("abc", "", 3)],
)
def test_levenshtein_is_correct_on_known_pairs(left, right, distance):
    assert levenshtein(left, right) == distance


# --- value comparison --------------------------------------------------------


@pytest.mark.parametrize(
    "expected, read",
    [("500 g", "500 g"), ("500 G", "500 g"), ("500  g", "500 g"), ("500 g.", "500 g")],
)
def test_shallow_differences_do_not_count_as_a_wrong_value(expected, read):
    counts = counts_for(
        truth("present_and_readable", expected),
        predicted({"reading": read}),
    )
    assert counts.value_correct == 1


def test_the_comparison_does_not_understand_unit_conversion():
    """A deliberate limit: `1 kg` vs `1000 g` is reported for a human to judge.

    Teaching the comparison to convert would be inventing a per-field metric
    definition, and docs/evaluation-strategy.md defines none.
    """
    counts = counts_for(
        truth("present_and_readable", "1 kg"), predicted({"base_quantity": 1000, "base_unit": "g"})
    )
    assert counts.value_incorrect == 1


def test_normalise_for_comparison_is_shallow_and_documented():
    assert normalise_for_comparison("  500  G. ") == "500 g"
    assert normalise_for_comparison("1 kg") != normalise_for_comparison("1000 g")


def test_a_two_part_value_matches_through_the_evidence_line():
    """The annotator writes the value; the extractor reports the whole line.

    A quantity normalises to `base_quantity` plus `base_unit`, which no single
    scalar comparison can match against the transcription `500 g`. Matching the
    evidence line is what stops every correctly read quantity being scored
    wrong - the defect this test was written for.
    """
    counts = counts_for(
        truth("present_and_readable", "500 g"),
        predicted(
            {"base_quantity": 500, "base_unit": "g"}, raw="Net Qty: 500 g"
        ),
    )
    assert counts.value_correct == 1


def test_a_value_absent_from_the_evidence_line_is_still_a_mismatch():
    """The evidence route must not credit anything the pipeline did not read."""
    counts = counts_for(
        truth("present_and_readable", "500 g"),
        predicted({"base_quantity": 250, "base_unit": "g"}, raw="Net Qty: 250 g"),
    )
    assert counts.value_incorrect == 1


# --- determinism and reporting ----------------------------------------------


def test_scoring_is_deterministic_for_deterministic_input():
    pairs = [
        (truth("present_and_readable", "500 g"), predicted({"base_quantity": 500})),
        (truth("not_present"), nothing_predicted()),
    ]
    assert score(pairs).as_dict() == score(pairs).as_dict()
    assert score(pairs).as_dict() == score(list(reversed(pairs))).as_dict()


def test_a_disagreement_records_both_sides_for_review():
    report = score(
        [(truth("present_but_unreadable"), predicted({"base_quantity": 500}))]
    )
    disagreement = report.as_dict()["disagreements"][0]

    assert disagreement["kind"] == "fabricated_value"
    assert disagreement["truth_state"] == "present_but_unreadable"
    assert disagreement["expected_value"] is None
    assert "500" in " ".join(disagreement["predicted_values"])
