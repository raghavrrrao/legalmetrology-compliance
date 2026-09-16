"""The abstaining-classifier metrics, checked by hand."""

from __future__ import annotations

import pytest

from labelextract.classification.metrics import compute_metrics


def test_perfect_predictions():
    metrics = compute_metrics(["a", "b", "a"], ["a", "b", "a"])
    assert metrics.strict_accuracy == 1.0
    assert metrics.accuracy_on_predicted == 1.0
    assert metrics.unknown_rate == 0.0
    assert metrics.macro_f1 == 1.0
    assert metrics.confusion == {
        "a": {"a": 2, "b": 0, "unknown": 0},
        "b": {"a": 0, "b": 1, "unknown": 0},
    }


def test_abstention_costs_recall_but_not_precision():
    metrics = compute_metrics(["a", "a", "a", "b"], ["a", None, "unknown", "b"])
    assert metrics.n_unknown == 2
    assert metrics.unknown_rate == 0.5
    assert metrics.strict_accuracy == 0.5
    assert metrics.accuracy_on_predicted == 1.0
    assert metrics.per_class["a"].precision == 1.0
    assert metrics.per_class["a"].recall == pytest.approx(1 / 3)
    assert metrics.confusion["a"]["unknown"] == 2


def test_a_class_never_predicted_has_zero_precision_and_is_named():
    metrics = compute_metrics(["a", "b", "b"], ["a", "a", "a"])
    assert metrics.per_class["b"].precision == 0.0
    assert metrics.per_class["b"].recall == 0.0
    assert metrics.undefined_precision == ("b",)
    assert metrics.per_class["a"].precision == pytest.approx(1 / 3)
    assert metrics.macro_precision == pytest.approx((1 / 3 + 0.0) / 2)


def test_macro_average_ignores_labels_absent_from_the_truth():
    metrics = compute_metrics(["a", "a"], ["a", "a"], labels=["a", "b"])
    assert metrics.labels == ("a",)
    assert metrics.macro_f1 == 1.0
    assert metrics.per_class["b"].support == 0


def test_a_prediction_outside_the_vocabulary_is_a_bug():
    with pytest.raises(ValueError, match="not among labels"):
        compute_metrics(["a"], ["z"])


def test_mismatched_lengths_are_refused():
    with pytest.raises(ValueError):
        compute_metrics(["a"], [])


def test_empty_input_yields_zeros_not_a_crash():
    metrics = compute_metrics([], [], labels=["a"])
    assert metrics.strict_accuracy == 0.0
    assert metrics.as_dict()["n_total"] == 0


def test_as_dict_is_rounded_and_json_shaped():
    body = compute_metrics(["a", "a", "b"], ["a", "b", "b"]).as_dict()
    assert body["strict_accuracy"] == pytest.approx(0.6667)
    assert set(body["per_class"]) == {"a", "b"}
    assert body["confusion"]["a"] == {"a": 1, "b": 1, "unknown": 0}
