"""What the pipeline said about one sample - kept deliberately apart from truth.

This is the prediction side of the evaluation, and it is a separate module from
`schema.py` for one reason: the two must never be constructed from each other.
`docs/data-strategy.md` requires the evaluation set to be "annotated
**independently of the system's output**", because "correcting the system's
guesses biases the ground truth toward the system". A codebase where a
prediction can be cast to an annotation is a codebase where that will
eventually happen in a hurry, the evening before a deadline.

So: annotations are parsed from files a person wrote; predictions are built
from an `ExtractionResult`; and there is no function anywhere that turns one
into the other.

The three prediction outcomes
-----------------------------
`labelextract` distinguishes three things for a given declaration, and the
distinction is the whole point of its design:

    a field with a committed value   "the label declares 500 g"
    a field with the value withheld  "a declaration is here; I will not guess"
    an unread declaration            "the label names this; I could not read it"
    (and nothing at all)             "I found no sign of this declaration"

A committed value is the only one that is a positive claim about the label, and
it is the only one scored as a detection. Collapsing the middle two into "found
it" would reward exactly the guessing the extractor refuses to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from labelextract.contracts import ExtractionResult, LabelFieldKey
from labelextract.fields import is_uncertain

#: Keys inside a normalised mapping that are bookkeeping rather than a reading.
#: A mapping carrying only these has no committed value - which is what the
#: extractor emits when it locates a declaration but refuses to pick a value.
_BOOKKEEPING_KEYS = frozenset(
    {"uncertain", "uncertainty_reasons", "candidates", "matched_by", "declaration"}
)


@dataclass(frozen=True)
class FieldPrediction:
    """One declaration as the pipeline reported it."""

    key: LabelFieldKey
    #: The evidence line, exactly as recognised. Never normalised here.
    raw_value: str
    normalized_value: Mapping[str, Any] | None
    confidence: float | None = None

    @property
    def has_committed_value(self) -> bool:
        """True when the pipeline actually committed to a reading.

        A field can be emitted with its value withheld - an ambiguous quantity,
        a reading `validation` withdrew - and that is not a claim that the
        label declares any particular thing. It is scored as "the declaration
        is present, no value asserted", never as a detection with a value.
        """
        if not self.normalized_value:
            return False
        return any(name not in _BOOKKEEPING_KEYS for name in self.normalized_value)

    @property
    def is_uncertain(self) -> bool:
        return bool(self.normalized_value) and is_uncertain(dict(self.normalized_value))

    @property
    def candidates(self) -> tuple[str, ...]:
        if not self.normalized_value:
            return ()
        raw = self.normalized_value.get("candidates") or ()
        return tuple(str(item) for item in raw)

    def comparable_values(self) -> tuple[str, ...]:
        """Strings that could reasonably be compared against an annotation.

        Returns every committed scalar in the normalised mapping plus the raw
        evidence line. Several rather than one, because there is no single
        "the value" across field types: a net quantity normalises to a number
        and a unit, a date to an ISO string, a name to a string. Picking one
        per key would be a per-field metric definition, and
        `docs/evaluation-strategy.md` does not define one - so the comparison
        is "does the annotator's transcription appear among what we read",
        which is checkable by hand from the report.
        """
        values: list[str] = []
        if self.normalized_value:
            for name, value in self.normalized_value.items():
                if name in _BOOKKEEPING_KEYS:
                    continue
                if isinstance(value, (str, int, float)):
                    values.append(str(value))
        if self.raw_value:
            values.append(self.raw_value)
        return tuple(values)


@dataclass(frozen=True)
class SamplePrediction:
    """Everything the pipeline produced for one photograph."""

    sample_id: str
    status: str
    engine_name: str
    engine_version: str
    #: Raw recognised text, before normalisation. CER and WER are computed
    #: against this: `docs/evaluation-strategy.md` requires the raw text,
    #: because normalising first "would measure the normaliser as well as the
    #: engine and hide the engine's errors behind it".
    recognised_text: str
    fields: tuple[FieldPrediction, ...] = ()
    #: Declarations the extractor saw named but could not read. Carried in the
    #: pipeline's run metadata; see `labelextract.pipeline`.
    unread_keys: frozenset[LabelFieldKey] = frozenset()
    processing_ms: int | None = None
    error_code: str | None = None

    def field(self, key: LabelFieldKey) -> FieldPrediction | None:
        for prediction in self.fields:
            if prediction.key == key:
                return prediction
        return None

    @classmethod
    def from_result(cls, sample_id: str, result: ExtractionResult) -> SamplePrediction:
        """Build from what the pipeline returned. The only constructor that reads a result."""
        unread: set[LabelFieldKey] = set()
        for item in (result.metadata or {}).get("unread_declarations", ()) or ():
            raw_key = item.get("key") if isinstance(item, Mapping) else None
            if raw_key is None:
                continue
            try:
                unread.add(LabelFieldKey(raw_key))
            except ValueError:
                # An engine reporting a key outside the vocabulary is a defect
                # in that engine, not something to score. Dropped here and
                # surfaced by the runner's own vocabulary check.
                continue

        return cls(
            sample_id=sample_id,
            status=result.status.value,
            engine_name=result.engine_name,
            engine_version=result.engine_version,
            recognised_text=result.ocr.full_text if result.ocr else "",
            fields=tuple(
                FieldPrediction(
                    key=extracted.key,
                    raw_value=extracted.raw_value,
                    normalized_value=(
                        dict(extracted.normalized_value)
                        if extracted.normalized_value is not None
                        else None
                    ),
                    confidence=extracted.confidence,
                )
                for extracted in result.fields
            ),
            unread_keys=frozenset(unread),
            processing_ms=result.processing_ms,
            error_code=result.error_code or None,
        )
