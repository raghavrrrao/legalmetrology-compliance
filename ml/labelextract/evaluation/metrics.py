"""Scoring predictions against ground truth, and refusing to score what it cannot.

Every metric here is one `docs/evaluation-strategy.md` already defines. None is
invented, and none is estimated: where the annotation needed for a metric does
not exist, the metric is reported as `None` with a stated reason rather than
computed from something cheaper that happens to be available.

The outcome table
-----------------
Four ground-truth states meet four prediction outcomes. The combinations are
not symmetric, and flattening them into "right / wrong" would hide the two
failures that matter most.

                            | predicted value | withheld / unread | nothing
    ------------------------|-----------------|-------------------|----------
    PRESENT_AND_READABLE    | true positive   | false negative    | false negative
    PRESENT_BUT_UNREADABLE  | FABRICATED      | correct           | missed unread
    NOT_PRESENT             | false positive  | false positive    | true negative
    UNKNOWN                 | excluded        | excluded          | excluded

Two cells deserve their names:

**FABRICATED** - the label names a declaration whose value a person could not
read, and the pipeline produced a value for it anyway. It is counted as a false
positive *and* reported separately, because it is the failure this entire
architecture exists to prevent: `field_presence` passes on any extracted field
regardless of its uncertainty flag, so a fabricated value turns a package that
declared nothing readable into one that declared something.

**UNKNOWN → excluded** - an un-annotated field is not a negative. Counting it as
NOT_PRESENT would charge the extractor for every gap in the annotation effort,
and the resulting precision would fall as annotation *improved*.

Which keys are scored
---------------------
Only `labelextract.fields.SUPPORTED_KEYS`. `docs/evaluation-strategy.md`:
"including those keys in an aggregate would produce a recall figure that is
really a measure of how many declarations we chose not to implement."
Annotations for unsupported keys are kept and counted as excluded, so the
ground truth is ready when an implementation lands.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field as dataclass_field
from typing import Iterable, Sequence

from labelextract.contracts import LabelFieldKey
from labelextract.evaluation.prediction import SamplePrediction
from labelextract.evaluation.schema import (
    FieldTruthState,
    SampleAnnotation,
    supported_keys_only,
)
from labelextract.fields import SUPPORTED_KEYS

_WHITESPACE = re.compile(r"\s+")


def normalise_for_comparison(text: str) -> str:
    """The one documented way a transcription is compared to a reading.

    Unicode-normalised, case-folded, whitespace-collapsed, surrounding
    punctuation stripped. Deliberately shallow: it absorbs the differences
    between `500 g`, `500  G` and `500 g.` and nothing else. It does **not**
    understand that `1 kg` and `1000 g` are the same quantity, and it must not
    learn to - that would be a per-field metric definition, and
    `docs/evaluation-strategy.md` defines none. A mismatch a human considers
    equivalent is listed in the report as a mismatch, for a human to judge.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _WHITESPACE.sub(" ", folded).strip(" \t.,:;-–—|/\\")


def levenshtein(hypothesis: Sequence, reference: Sequence) -> int:
    """Edit distance, iterative with two rows. Stdlib only, deterministic."""
    if hypothesis == reference:
        return 0
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    previous = list(range(len(reference) + 1))
    for i, hypothesis_item in enumerate(hypothesis, start=1):
        current = [i]
        for j, reference_item in enumerate(reference, start=1):
            current.append(
                min(
                    previous[j] + 1,                                   # deletion
                    current[j - 1] + 1,                                # insertion
                    previous[j - 1] + (hypothesis_item != reference_item),  # substitution
                )
            )
        previous = current
    return previous[-1]


@dataclass
class FieldCounts:
    """The outcome table for one `LabelFieldKey`, as raw counts."""

    key: LabelFieldKey
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0
    #: False positives whose ground truth is PRESENT_BUT_UNREADABLE. A subset
    #: of `false_positive`, never added on top of it.
    fabricated: int = 0
    #: Ground truth PRESENT_BUT_UNREADABLE, and the pipeline correctly declined
    #: to produce a value (withheld it, or reported it unread).
    correct_unread: int = 0
    #: Ground truth PRESENT_BUT_UNREADABLE and the pipeline saw nothing at all.
    #: Not a value error - there was no readable value - but the declaration
    #: was missed, which a retake would have caught.
    missed_unread: int = 0
    #: Detected with a value, and the value matched the transcription.
    value_correct: int = 0
    #: Detected with a value that did not match. Listed in the report so a
    #: person can see whether the metric or the reading is at fault.
    value_incorrect: int = 0
    #: Ground truth UNKNOWN, or the key is unsupported. Scored nowhere.
    excluded: int = 0

    @property
    def precision(self) -> float | None:
        """Of the values we reported, how many the label actually declared."""
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        """Of the readable declarations present, how many we reported."""
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def value_accuracy(self) -> float | None:
        """Of the declarations found, how many had the right value."""
        denominator = self.value_correct + self.value_incorrect
        return self.value_correct / denominator if denominator else None

    def as_dict(self) -> dict:
        return {
            "key": self.key.value,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "true_negative": self.true_negative,
            "fabricated": self.fabricated,
            "correct_unread": self.correct_unread,
            "missed_unread": self.missed_unread,
            "value_correct": self.value_correct,
            "value_incorrect": self.value_incorrect,
            "excluded": self.excluded,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "value_accuracy": self.value_accuracy,
        }


@dataclass
class UncertaintyCounts:
    """The three uncertainty metrics `docs/evaluation-strategy.md` names.

    **The three do not share a denominator, and that is deliberate.** Each is
    stated below next to the counter it divides by, because reading one of
    these rates against the wrong population is how an uncertainty number
    becomes a lie.

    `uncertain_rate` counts **every emitted field**, committed or withheld.
    This is the doc's wording - "proportion of extracted fields flagged
    `uncertain`" - and it matters: a withheld reading is emitted *because* the
    extractor could not commit, and it is always flagged. Excluding those would
    report `uncertain_rate = 0.0` for a set where the extractor hedged on half
    the declarations, which is the opposite of the truth.

    `uncertainty_precision` and `silent_error_rate` count only **committed
    readings**, because both ask whether a reading was *wrong*, and a withheld
    reading asserts nothing that could be wrong. A withheld field is neither a
    silent error nor a mis-flag; it is the extractor working as designed.
    """

    #: Every field the pipeline emitted for a scored key - the denominator of
    #: `uncertain_rate`.
    extracted_fields: int = 0
    #: Of those, how many carry `uncertain: True`. Committed or withheld.
    flagged_uncertain: int = 0
    #: Emitted *with* a committed value. Separate from `extracted_fields`
    #: because the two rates below are only meaningful over these.
    committed_readings: int = 0
    #: Committed, flagged uncertain - the denominator of
    #: `uncertainty_precision`.
    flagged_uncertain_committed: int = 0
    #: Committed, flagged uncertain, and genuinely wrong (a false positive, a
    #: fabrication, or a value that did not match).
    uncertain_and_wrong: int = 0
    #: Committed, NOT flagged, and wrong anyway. "The last one is the number
    #: that matters. A confident wrong reading is the failure this whole design
    #: exists to avoid."
    confident_and_wrong: int = 0
    confident_total: int = 0

    @property
    def uncertain_rate(self) -> float | None:
        """Flagged uncertain, over every emitted field."""
        return (
            self.flagged_uncertain / self.extracted_fields
            if self.extracted_fields
            else None
        )

    @property
    def uncertainty_precision(self) -> float | None:
        """Of the committed readings we flagged, how many really were wrong."""
        return (
            self.uncertain_and_wrong / self.flagged_uncertain_committed
            if self.flagged_uncertain_committed
            else None
        )

    @property
    def silent_error_rate(self) -> float | None:
        """Of the committed readings we did NOT flag, how many were wrong."""
        return (
            self.confident_and_wrong / self.confident_total
            if self.confident_total
            else None
        )

    def as_dict(self) -> dict:
        return {
            "extracted_fields": self.extracted_fields,
            "flagged_uncertain": self.flagged_uncertain,
            "committed_readings": self.committed_readings,
            "flagged_uncertain_committed": self.flagged_uncertain_committed,
            "uncertain_and_wrong": self.uncertain_and_wrong,
            "confident_and_wrong": self.confident_and_wrong,
            "confident_total": self.confident_total,
            "uncertain_rate": self.uncertain_rate,
            "uncertainty_precision": self.uncertainty_precision,
            "silent_error_rate": self.silent_error_rate,
            "denominators": {
                "uncertain_rate": "extracted_fields",
                "uncertainty_precision": "flagged_uncertain_committed",
                "silent_error_rate": "confident_total",
            },
        }


@dataclass
class TextAccuracy:
    """CER and WER, or an explicit statement that they cannot be computed."""

    scored_samples: int = 0
    skipped_samples: int = 0
    character_errors: int = 0
    reference_characters: int = 0
    word_errors: int = 0
    reference_words: int = 0

    @property
    def cer(self) -> float | None:
        return (
            self.character_errors / self.reference_characters
            if self.reference_characters
            else None
        )

    @property
    def wer(self) -> float | None:
        return self.word_errors / self.reference_words if self.reference_words else None

    def as_dict(self) -> dict:
        unavailable = None
        if self.scored_samples == 0:
            unavailable = (
                "no sample carries a hand-transcribed reference_text, so CER and "
                "WER cannot be computed. They are unavailable, not zero."
            )
        return {
            "scored_samples": self.scored_samples,
            "skipped_samples": self.skipped_samples,
            "character_errors": self.character_errors,
            "reference_characters": self.reference_characters,
            "word_errors": self.word_errors,
            "reference_words": self.reference_words,
            "cer": self.cer,
            "wer": self.wer,
            "unavailable_reason": unavailable,
        }


@dataclass
class Disagreement:
    """One scored cell worth a human's attention, recorded in full."""

    sample_id: str
    key: str
    kind: str
    truth_state: str
    expected_value: str | None
    predicted_values: tuple[str, ...]
    uncertain: bool

    def as_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "key": self.key,
            "kind": self.kind,
            "truth_state": self.truth_state,
            "expected_value": self.expected_value,
            "predicted_values": list(self.predicted_values),
            "uncertain": self.uncertain,
        }


@dataclass
class ScoreReport:
    """Everything one evaluation run measured."""

    per_field: dict[LabelFieldKey, FieldCounts] = dataclass_field(default_factory=dict)
    uncertainty: UncertaintyCounts = dataclass_field(default_factory=UncertaintyCounts)
    text: TextAccuracy = dataclass_field(default_factory=TextAccuracy)
    disagreements: list[Disagreement] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            # Sorted so two runs over the same data produce byte-identical
            # reports: a diff between runs should show a change in the numbers,
            # never a change in dictionary ordering.
            "per_field": [
                self.per_field[key].as_dict()
                for key in sorted(self.per_field, key=lambda k: k.value)
            ],
            "uncertainty": self.uncertainty.as_dict(),
            "text_accuracy": self.text.as_dict(),
            "disagreements": [
                item.as_dict()
                for item in sorted(
                    self.disagreements, key=lambda d: (d.sample_id, d.key, d.kind)
                )
            ],
        }


def _value_matches(expected: str, predicted_values: Iterable[str], evidence: str) -> bool:
    """Whether the annotator's transcription matches what the pipeline read.

    Two ways to match, and the second one is not laziness:

    1. **Exact**, after `normalise_for_comparison`, against any committed
       scalar in the normalised mapping.
    2. **Contained in the evidence line**, again after normalisation.

    The second exists because the two sides describe the same thing at
    different scopes, systematically. An annotator transcribes the *value* -
    `500 g`. The extractor's evidence line is the whole printed line it read
    the value from - `Net Qty: 500 g`. And the normalised mapping splits that
    value across `base_quantity` and `base_unit`, so exact-matching scalars
    alone can never match a two-part value and would report every correctly
    read quantity as wrong.

    Deliberately **not** done here: understanding that `1 kg` and `1000 g` are
    the same quantity. That would be a per-field metric definition, and
    `docs/evaluation-strategy.md` defines none - so an equivalence a human
    would accept is recorded as a mismatch in `disagreements` for a human to
    judge, rather than decided by this function.

    The known cost of rule 2: a transcription that happens to appear elsewhere
    in the same evidence line is credited. The line has already been located as
    this declaration, which bounds the damage, but a value accuracy computed
    this way is an upper bound and should be read as one.
    """
    target = normalise_for_comparison(expected)
    if not target:
        return False
    if any(normalise_for_comparison(value) == target for value in predicted_values):
        return True
    return target in normalise_for_comparison(evidence)


def score(
    pairs: Sequence[tuple[SampleAnnotation, SamplePrediction]],
) -> ScoreReport:
    """Score annotation/prediction pairs. Pure, deterministic, order-independent.

    Args:
        pairs: one `(annotation, prediction)` per sample. The two are separate
            types on purpose; see `prediction.py`.
    """
    report = ScoreReport()
    for key in sorted(SUPPORTED_KEYS, key=lambda k: k.value):
        report.per_field[key] = FieldCounts(key=key)

    for annotation, prediction in pairs:
        _score_sample(annotation, prediction, report)
        _score_text(annotation, prediction, report.text)

    return report


def _score_sample(
    annotation: SampleAnnotation,
    prediction: SamplePrediction,
    report: ScoreReport,
) -> None:
    # Annotations for keys the extractor does not attempt are counted as
    # excluded rather than dropped, so the report shows the ground truth exists
    # and is simply not scorable yet.
    for unsupported in set(annotation.annotated_keys) - set(SUPPORTED_KEYS):
        counts = report.per_field.setdefault(unsupported, FieldCounts(key=unsupported))
        counts.excluded += 1

    for key in supported_keys_only(tuple(LabelFieldKey)):
        truth = annotation.field(key)
        predicted = prediction.field(key)
        counts = report.per_field[key]

        has_value = predicted is not None and predicted.has_committed_value
        # "Declared present without a value" and "reported unread" are both the
        # pipeline declining to guess, and are scored the same way.
        declined = (
            predicted is not None and not predicted.has_committed_value
        ) or key in prediction.unread_keys
        uncertain = bool(predicted and predicted.is_uncertain)
        predicted_values = predicted.comparable_values() if predicted else ()

        def record(kind: str) -> None:
            report.disagreements.append(
                Disagreement(
                    sample_id=annotation.sample_id,
                    key=key.value,
                    kind=kind,
                    truth_state=truth.state.value,
                    expected_value=truth.value,
                    predicted_values=predicted_values,
                    uncertain=uncertain,
                )
            )

        wrong = False

        if truth.state is FieldTruthState.UNKNOWN:
            counts.excluded += 1
            continue

        if truth.state is FieldTruthState.PRESENT_AND_READABLE:
            if has_value:
                counts.true_positive += 1
                if _value_matches(
                    truth.value or "", predicted_values, predicted.raw_value if predicted else ""
                ):
                    counts.value_correct += 1
                else:
                    counts.value_incorrect += 1
                    wrong = True
                    record("wrong_value")
            else:
                counts.false_negative += 1
                record("missed_readable_declaration")

        elif truth.state is FieldTruthState.PRESENT_BUT_UNREADABLE:
            if has_value:
                counts.false_positive += 1
                counts.fabricated += 1
                wrong = True
                record("fabricated_value")
            elif declined:
                counts.correct_unread += 1
            else:
                counts.missed_unread += 1
                record("missed_unread_declaration")

        elif truth.state is FieldTruthState.NOT_PRESENT:
            if has_value:
                counts.false_positive += 1
                wrong = True
                record("value_for_absent_declaration")
            elif declined:
                counts.false_positive += 1
                wrong = True
                record("named_an_absent_declaration")
            else:
                counts.true_negative += 1

        # Every emitted field counts toward `uncertain_rate`, including one
        # whose value was withheld - that field exists precisely because the
        # extractor declined to commit, and it is always flagged uncertain.
        if predicted is not None:
            report.uncertainty.extracted_fields += 1
            if uncertain:
                report.uncertainty.flagged_uncertain += 1

        # The other two rates ask whether a reading was wrong, so they count
        # only readings that asserted something.
        if has_value:
            report.uncertainty.committed_readings += 1
            if uncertain:
                report.uncertainty.flagged_uncertain_committed += 1
                if wrong:
                    report.uncertainty.uncertain_and_wrong += 1
            else:
                report.uncertainty.confident_total += 1
                if wrong:
                    report.uncertainty.confident_and_wrong += 1


def _score_text(
    annotation: SampleAnnotation,
    prediction: SamplePrediction,
    accuracy: TextAccuracy,
) -> None:
    """CER and WER against a hand transcription, when one exists.

    Per `docs/evaluation-strategy.md`: computed on the **raw** OCR text before
    normalisation, case-sensitive, whitespace-normalised.
    """
    reference = annotation.reference_text
    if reference is None:
        accuracy.skipped_samples += 1
        return

    reference_text = _WHITESPACE.sub(" ", reference).strip()
    hypothesis_text = _WHITESPACE.sub(" ", prediction.recognised_text).strip()
    if not reference_text:
        # An empty transcription cannot produce a rate - the denominator is
        # zero - and guessing one would be inventing a measurement.
        accuracy.skipped_samples += 1
        return

    accuracy.scored_samples += 1
    accuracy.character_errors += levenshtein(hypothesis_text, reference_text)
    accuracy.reference_characters += len(reference_text)

    reference_words = reference_text.split(" ")
    hypothesis_words = hypothesis_text.split(" ") if hypothesis_text else []
    accuracy.word_errors += levenshtein(hypothesis_words, reference_words)
    accuracy.reference_words += len(reference_words)
