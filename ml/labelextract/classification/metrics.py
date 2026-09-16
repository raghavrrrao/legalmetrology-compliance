"""Classification metrics for a classifier that is allowed to abstain.

A classifier with an UNKNOWN outcome needs one more number than the usual
four, and needs the usual four defined carefully, because an abstention is
neither a correct answer nor a wrong one in the ordinary sense:

- **`unknown_rate`** - the share of examples the classifier declined.
- **`strict_accuracy`** - correct / all examples. An abstention counts as
  wrong. This is the number to quote when asking "how often does it give
  the right answer".
- **`accuracy_on_predicted`** - correct / examples it did answer. This is
  the number to quote when asking "when it commits, how often is it right",
  and it is meaningless without the unknown rate beside it: a classifier
  that answers one example correctly and abstains on the rest scores 1.0.
- **Per-class precision** is computed over committed predictions only - an
  abstention is not a prediction of any class - and **per-class recall**
  counts abstentions as misses, because the classifier failed to identify
  that class. So recall is penalised by abstaining and precision is not,
  which is the trade-off an abstaining classifier makes on purpose.
- **Macro averages** are over the classes present in the ground truth. A
  class with no committed prediction has undefined precision; it is
  reported as 0.0 and named in `undefined_precision`, rather than silently
  dropped from the average, which would inflate it.

The confusion matrix has one column more than it has rows: the `unknown`
column, so that abstentions are visible per true class rather than folded
into a single count.

Pure Python, no dependencies, so the same code scores the trainer's
cross-validation and any test that wants to check a number by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from labelextract.contracts import UNKNOWN_CATEGORY


@dataclass(frozen=True)
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int
    predicted: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "support": self.support,
            "predicted": self.predicted,
        }


@dataclass(frozen=True)
class ClassificationMetrics:
    n_total: int
    n_predicted: int
    n_unknown: int
    n_correct: int
    labels: tuple[str, ...]
    per_class: dict[str, ClassMetrics]
    confusion: dict[str, dict[str, int]]
    undefined_precision: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unknown_rate(self) -> float:
        return self.n_unknown / self.n_total if self.n_total else 0.0

    @property
    def strict_accuracy(self) -> float:
        return self.n_correct / self.n_total if self.n_total else 0.0

    @property
    def accuracy_on_predicted(self) -> float:
        return self.n_correct / self.n_predicted if self.n_predicted else 0.0

    def _macro(self, attribute: str) -> float:
        if not self.labels:
            return 0.0
        return sum(getattr(self.per_class[label], attribute) for label in self.labels) / len(self.labels)

    @property
    def macro_precision(self) -> float:
        return self._macro("precision")

    @property
    def macro_recall(self) -> float:
        return self._macro("recall")

    @property
    def macro_f1(self) -> float:
        return self._macro("f1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_total": self.n_total,
            "n_predicted": self.n_predicted,
            "n_unknown": self.n_unknown,
            "n_correct": self.n_correct,
            "unknown_rate": round(self.unknown_rate, 4),
            "strict_accuracy": round(self.strict_accuracy, 4),
            "accuracy_on_predicted": round(self.accuracy_on_predicted, 4),
            "macro_precision": round(self.macro_precision, 4),
            "macro_recall": round(self.macro_recall, 4),
            "macro_f1": round(self.macro_f1, 4),
            "undefined_precision": list(self.undefined_precision),
            "per_class": {name: item.as_dict() for name, item in self.per_class.items()},
            "confusion": {truth: dict(row) for truth, row in self.confusion.items()},
        }


def compute_metrics(
    truths: Sequence[str],
    predictions: Sequence[str | None],
    *,
    labels: Sequence[str] | None = None,
) -> ClassificationMetrics:
    """Score `predictions` against `truths`.

    A prediction of `None` or `UNKNOWN_CATEGORY` is an abstention. `labels`
    defaults to the sorted set of ground-truth classes; pass it to score
    against a fixed vocabulary (a class the truth never contains then has
    support 0 and is excluded from the macro averages).
    """
    if len(truths) != len(predictions):
        raise ValueError("truths and predictions must have the same length")
    normalised = [
        UNKNOWN_CATEGORY if prediction is None else prediction
        for prediction in predictions
    ]
    if labels is None:
        labels = sorted(set(truths))
    else:
        labels = list(labels)
    columns = [*labels, UNKNOWN_CATEGORY]

    confusion: dict[str, dict[str, int]] = {
        truth: {column: 0 for column in columns} for truth in labels
    }
    for truth, prediction in zip(truths, normalised):
        if truth not in confusion:
            raise ValueError(f"truth {truth!r} is not among labels {labels}")
        if prediction not in confusion[truth]:
            # A prediction outside the vocabulary is a bug in the caller, not
            # a metric to absorb.
            raise ValueError(f"prediction {prediction!r} is not among labels {labels}")
        confusion[truth][prediction] += 1

    n_total = len(truths)
    n_unknown = sum(1 for prediction in normalised if prediction == UNKNOWN_CATEGORY)
    n_correct = sum(1 for truth, prediction in zip(truths, normalised) if truth == prediction)

    per_class: dict[str, ClassMetrics] = {}
    undefined: list[str] = []
    scored_labels: list[str] = []
    for label in labels:
        support = sum(confusion[label].values())
        predicted = sum(confusion[truth][label] for truth in labels)
        true_positive = confusion[label][label]
        if predicted:
            precision = true_positive / predicted
        else:
            precision = 0.0
            if support:
                undefined.append(label)
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0 else 0.0
        )
        per_class[label] = ClassMetrics(
            precision=precision, recall=recall, f1=f1,
            support=support, predicted=predicted,
        )
        if support:
            scored_labels.append(label)

    return ClassificationMetrics(
        n_total=n_total,
        n_predicted=n_total - n_unknown,
        n_unknown=n_unknown,
        n_correct=n_correct,
        labels=tuple(scored_labels),
        per_class=per_class,
        confusion=confusion,
        undefined_precision=tuple(undefined),
    )
