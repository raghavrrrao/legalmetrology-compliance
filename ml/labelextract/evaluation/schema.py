"""The shape of a frozen evaluation sample, and what makes one invalid.

This module defines ground truth. Nothing here runs the pipeline, and nothing
here is allowed to guess: every parser below rejects what it does not
understand rather than filling in a default, because a silently defaulted
annotation becomes a number somebody later quotes.

Why the field states are four, not two
--------------------------------------
The obvious design is "expected value, or null". It is wrong, and the way it is
wrong is the reason this project exists. A null would merge four different
facts about a label:

    PRESENT_AND_READABLE     the declaration is printed and its value is legible
    PRESENT_BUT_UNREADABLE   the declaration is named; its value cannot be read
    NOT_PRESENT              the declaration is not on this panel at all
    UNKNOWN                  nobody has annotated this field yet

Scoring them together produces nonsense in both directions. A pipeline that
reports nothing for a PRESENT_BUT_UNREADABLE declaration is *correct* - the
value genuinely cannot be read - while one that reports a value for it has
fabricated a declaration, which is the single worst failure this system can
produce. And UNKNOWN is not a negative: counting un-annotated fields as
NOT_PRESENT would turn every gap in the annotation effort into a false
positive against the extractor.

`labelextract` already draws the same distinction on the prediction side - a
field with a value, an unread declaration, and nothing at all are three
different outputs - so scoring against a two-state truth would throw away
information the extractor took care to produce.

Ground truth is not prediction
------------------------------
Nothing in this module reads an `ExtractionResult`, and no constructor here
accepts one. Annotations are written by a person, recorded with who wrote them
and when, and `docs/data-strategy.md` is explicit that annotating by correcting
the system's guesses biases the truth toward the system. The type system is the
cheapest place to keep the two apart, so they are separate types that never
convert into one another.

Scope
-----
This is *extraction* ground truth: what is printed on the package. It is
deliberately not compliance ground truth. Whether a declaration was legally
required is decided by verified `ComplianceRule` rows in the deterministic
engine, and `ml/data/README.md` states plainly that a folder name or filename
is never a finding. No field in this schema records a compliance verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from labelextract.contracts import LabelFieldKey
from labelextract.fields import SUPPORTED_KEYS


class EvaluationDataError(ValueError):
    """A dataset, manifest or annotation is malformed.

    Raised rather than repaired, always. `docs/evaluation-strategy.md` requires
    that a published number name its dataset; a dataset this module quietly
    fixed up is not the dataset anyone reviewed.
    """


class FieldTruthState(str, Enum):
    """What a person established about one declaration on one photograph."""

    #: Printed, and its value is legible to a human reading the photograph.
    PRESENT_AND_READABLE = "present_and_readable"
    #: The declaration is named on the panel but its value cannot be read -
    #: glare, a fold, a crop, print too small to resolve. The correct pipeline
    #: behaviour is to report the declaration unread, never to invent a value.
    PRESENT_BUT_UNREADABLE = "present_but_unreadable"
    #: Not on this panel. A photograph shows one panel, so this is a fact about
    #: the photograph and not about the product.
    NOT_PRESENT = "not_present"
    #: Nobody has annotated this field for this sample. Scored as excluded, and
    #: never as a negative - see the module docstring.
    UNKNOWN = "unknown"


#: States that carry an expected value. Any other state with a `value` set is
#: rejected: "unreadable, and the value is 500 g" is a contradiction, and it is
#: exactly the contradiction that appears when somebody pastes an OCR reading
#: into an annotation they could not actually verify.
_STATES_WITH_A_VALUE = frozenset({FieldTruthState.PRESENT_AND_READABLE})

#: A dataset version is an opaque, explicit label. Deliberately not derived
#: from a date or a timestamp: the invariant that matters is that a published
#: result names a version whose contents cannot have changed underneath it, and
#: a date-based version silently re-labels a set that was edited the same day.
#: Kept restrictive so a version is safe in a filename and a report.
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")

#: A sample identifier. Stable across dataset versions where the sample is the
#: same photograph, so a per-sample result can be compared between runs.
_SAMPLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")

#: Lowercase SHA-256, as `sha256sum` prints it.
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: An ISO date, `YYYY-MM-DD`. Parsed only far enough to reject a free-text
#: "last Tuesday"; the value is kept as the string the annotator wrote.
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvaluationDataError(message)


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{what} must be a JSON object, got {type(value).__name__}")
    return value


def _require_str(source: Mapping[str, Any], key: str, what: str) -> str:
    value = source.get(key)
    _require(
        isinstance(value, str) and value.strip() != "",
        f"{what} requires a non-empty string {key!r}",
    )
    return value


@dataclass(frozen=True)
class FieldAnnotation:
    """One declaration, as a person read it off one photograph."""

    key: LabelFieldKey
    state: FieldTruthState
    #: The declared value in the annotator's own transcription, present only
    #: when the state is PRESENT_AND_READABLE. Compared against the pipeline's
    #: reading; never used to produce one.
    value: str | None = None
    #: Free-text note from the annotator - why a field was marked unreadable,
    #: what made a reading ambiguous. Never scored; read by a human reviewing a
    #: disagreement.
    note: str = ""

    def __post_init__(self) -> None:
        _require(
            isinstance(self.key, LabelFieldKey),
            f"field key must be a LabelFieldKey, got {self.key!r}",
        )
        _require(
            isinstance(self.state, FieldTruthState),
            f"field state must be a FieldTruthState, got {self.state!r}",
        )
        if self.state in _STATES_WITH_A_VALUE:
            _require(
                self.value is not None and self.value.strip() != "",
                f"{self.key.value} is {self.state.value} so it must carry the value "
                f"the annotator read; use {FieldTruthState.PRESENT_BUT_UNREADABLE.value} "
                f"if the declaration is printed but its value is not legible",
            )
        else:
            _require(
                self.value is None,
                f"{self.key.value} is {self.state.value} so it must not carry a value; "
                f"a value on a non-readable state is a reading nobody verified",
            )

    @classmethod
    def from_dict(cls, payload: Any) -> FieldAnnotation:
        data = _require_mapping(payload, "a field annotation")

        raw_key = _require_str(data, "key", "a field annotation")
        try:
            key = LabelFieldKey(raw_key)
        except ValueError:
            raise EvaluationDataError(
                f"{raw_key!r} is not a LabelFieldKey. The evaluation vocabulary is "
                f"the extraction vocabulary; adding a declaration here without adding "
                f"it to labelextract.contracts would score the extractor against a "
                f"field it has never heard of. Known keys: "
                f"{sorted(k.value for k in LabelFieldKey)}"
            ) from None

        raw_state = _require_str(data, "state", f"field {raw_key}")
        try:
            state = FieldTruthState(raw_state)
        except ValueError:
            raise EvaluationDataError(
                f"{raw_state!r} is not a valid annotation state for {raw_key}. "
                f"Valid states: {[s.value for s in FieldTruthState]}"
            ) from None

        value = data.get("value")
        _require(
            value is None or isinstance(value, str),
            f"field {raw_key}: 'value' must be a string or absent",
        )
        note = data.get("note", "")
        _require(isinstance(note, str), f"field {raw_key}: 'note' must be a string")

        unexpected = set(data) - {"key", "state", "value", "note"}
        _require(
            not unexpected,
            f"field {raw_key}: unexpected annotation keys {sorted(unexpected)}. "
            f"An unrecognised key is more likely a typo than an extension, and a "
            f"typo in ground truth is invisible once it is a number.",
        )

        return cls(key=key, state=state, value=value, note=note)


@dataclass(frozen=True)
class SampleAnnotation:
    """Ground truth for one photograph, and who established it."""

    sample_id: str
    #: Who annotated this sample, and on what date. `docs/data-strategy.md`
    #: requires provenance per image: "Provenance that lives only in one
    #: person's memory is not provenance."
    annotated_by: str
    annotated_on: str
    fields: tuple[FieldAnnotation, ...] = ()
    #: The full printed text of the panel, transcribed by hand, when somebody
    #: has done that work. Optional because it is expensive: it is what CER and
    #: WER need, and those metrics are simply unavailable without it rather
    #: than approximated from something cheaper.
    reference_text: str | None = None
    #: Photograph conditions, for the per-condition reporting
    #: `docs/evaluation-strategy.md` requires ("an average over easy and hard
    #: images hides exactly the cases that matter"). Free-form labels agreed by
    #: the annotators; not validated against a fixed list, because the useful
    #: conditions are discovered while annotating.
    conditions: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        _require(
            bool(_SAMPLE_ID_PATTERN.match(self.sample_id)),
            f"{self.sample_id!r} is not a usable sample id (letters, digits, "
            f"dot, dash, underscore; up to 128 characters)",
        )
        _require(
            self.annotated_by.strip() != "",
            f"{self.sample_id}: 'annotated_by' is required - an annotation with "
            f"no author cannot be questioned later",
        )
        _require(
            bool(_DATE_PATTERN.match(self.annotated_on)),
            f"{self.sample_id}: 'annotated_on' must be an ISO date (YYYY-MM-DD), "
            f"got {self.annotated_on!r}",
        )
        seen: set[LabelFieldKey] = set()
        for annotation in self.fields:
            _require(
                annotation.key not in seen,
                f"{self.sample_id}: {annotation.key.value} is annotated more than "
                f"once. Two annotations for one declaration on one photograph "
                f"cannot both be ground truth.",
            )
            seen.add(annotation.key)

    def field(self, key: LabelFieldKey) -> FieldAnnotation:
        """The annotation for `key`, or an explicit UNKNOWN if there is none.

        Absence means "not annotated", never "not present". Returning UNKNOWN
        rather than None is what stops a caller from treating a gap in the
        annotation effort as a negative and charging the extractor for it.
        """
        for annotation in self.fields:
            if annotation.key == key:
                return annotation
        return FieldAnnotation(key=key, state=FieldTruthState.UNKNOWN)

    @property
    def annotated_keys(self) -> frozenset[LabelFieldKey]:
        return frozenset(annotation.key for annotation in self.fields)

    @classmethod
    def from_dict(cls, payload: Any) -> SampleAnnotation:
        data = _require_mapping(payload, "an annotation file")

        sample_id = _require_str(data, "sample_id", "an annotation file")
        annotated_by = _require_str(data, "annotated_by", f"annotation {sample_id}")
        annotated_on = _require_str(data, "annotated_on", f"annotation {sample_id}")

        raw_fields = data.get("fields", [])
        _require(
            isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)),
            f"annotation {sample_id}: 'fields' must be a list",
        )

        reference_text = data.get("reference_text")
        _require(
            reference_text is None or isinstance(reference_text, str),
            f"annotation {sample_id}: 'reference_text' must be a string or absent",
        )

        raw_conditions = data.get("conditions", [])
        _require(
            isinstance(raw_conditions, Sequence)
            and not isinstance(raw_conditions, (str, bytes))
            and all(isinstance(c, str) for c in raw_conditions),
            f"annotation {sample_id}: 'conditions' must be a list of strings",
        )

        note = data.get("note", "")
        _require(isinstance(note, str), f"annotation {sample_id}: 'note' must be a string")

        unexpected = set(data) - {
            "sample_id", "annotated_by", "annotated_on", "fields",
            "reference_text", "conditions", "note",
        }
        _require(
            not unexpected,
            f"annotation {sample_id}: unexpected keys {sorted(unexpected)}",
        )

        return cls(
            sample_id=sample_id,
            annotated_by=annotated_by,
            annotated_on=annotated_on,
            fields=tuple(FieldAnnotation.from_dict(item) for item in raw_fields),
            reference_text=reference_text,
            conditions=tuple(raw_conditions),
            note=note,
        )


@dataclass(frozen=True)
class SampleEntry:
    """One row of the manifest: which photograph, and which annotation file."""

    sample_id: str
    #: Path to the image, relative to the dataset root. Relative on purpose:
    #: an absolute path in a manifest is reproducible on exactly one machine.
    image: str
    #: Path to the annotation file, relative to the dataset root.
    annotation: str
    #: SHA-256 of the image bytes. This is what makes "frozen" enforceable
    #: rather than a promise: an edited or replaced photograph changes the
    #: digest, validation fails, and the dataset has to be re-versioned instead
    #: of silently invalidating every number already published against it.
    image_sha256: str

    def __post_init__(self) -> None:
        _require(
            bool(_SAMPLE_ID_PATTERN.match(self.sample_id)),
            f"{self.sample_id!r} is not a usable sample id",
        )
        for name, value in (("image", self.image), ("annotation", self.annotation)):
            _require(value.strip() != "", f"{self.sample_id}: {name!r} is required")
            # Manifest paths are relative POSIX paths, forward slashes only.
            #
            # The backslash rejection is load bearing and was missed on the
            # first pass: the guard below used to split on "/" alone, so
            # `..\..\windows\system32` contained no ".." *segment* by that
            # reckoning and was accepted - and on Windows, where most of this
            # team develops, `root / that` really does resolve outside the
            # dataset. Refusing the separator outright is simpler than
            # normalising it, and costs nothing: a manifest that spells a path
            # with backslashes is not portable anyway.
            _require(
                "\\" not in value,
                f"{self.sample_id}: {name} {value!r} uses a backslash. Manifest "
                f"paths are relative POSIX paths - use '/' so the same manifest "
                f"resolves identically on every machine.",
            )
            _require(
                not value.startswith("/") and ".." not in value.split("/"),
                f"{self.sample_id}: {name} {value!r} must be a relative path inside "
                f"the dataset, with no '..' segment",
            )
        _require(
            bool(_SHA256_PATTERN.match(self.image_sha256)),
            f"{self.sample_id}: 'image_sha256' must be 64 lowercase hex characters, "
            f"got {self.image_sha256!r}",
        )

    @classmethod
    def from_dict(cls, payload: Any) -> SampleEntry:
        data = _require_mapping(payload, "a manifest sample entry")
        sample_id = _require_str(data, "sample_id", "a manifest sample entry")
        unexpected = set(data) - {"sample_id", "image", "annotation", "image_sha256"}
        _require(
            not unexpected,
            f"manifest sample {sample_id}: unexpected keys {sorted(unexpected)}",
        )
        return cls(
            sample_id=sample_id,
            image=_require_str(data, "image", f"manifest sample {sample_id}"),
            annotation=_require_str(data, "annotation", f"manifest sample {sample_id}"),
            image_sha256=_require_str(data, "image_sha256", f"manifest sample {sample_id}"),
        )


@dataclass(frozen=True)
class DatasetManifest:
    """The frozen set's identity and contents.

    The identity half - `dataset_version` plus a digest per image - is what
    lets a published number be checked. `docs/evaluation-strategy.md` requires
    every result to name its dataset, its size and its date; a result that
    names a version whose images can have been swapped names nothing.
    """

    dataset_version: str
    created_on: str
    description: str = ""
    samples: tuple[SampleEntry, ...] = ()

    def __post_init__(self) -> None:
        _require(
            bool(_VERSION_PATTERN.match(self.dataset_version)),
            f"{self.dataset_version!r} is not a usable dataset version (letters, "
            f"digits, dot, dash, underscore; up to 64 characters)",
        )
        _require(
            bool(_DATE_PATTERN.match(self.created_on)),
            f"dataset {self.dataset_version}: 'created_on' must be an ISO date "
            f"(YYYY-MM-DD), got {self.created_on!r}",
        )
        seen: dict[str, int] = {}
        for index, entry in enumerate(self.samples):
            _require(
                entry.sample_id not in seen,
                f"dataset {self.dataset_version}: duplicate sample_id "
                f"{entry.sample_id!r} at positions {seen.get(entry.sample_id)} and "
                f"{index}. A duplicated sample is counted twice in every metric.",
            )
            seen[entry.sample_id] = index

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @classmethod
    def from_dict(cls, payload: Any) -> DatasetManifest:
        data = _require_mapping(payload, "a dataset manifest")
        dataset_version = _require_str(data, "dataset_version", "a dataset manifest")
        created_on = _require_str(data, "created_on", f"dataset {dataset_version}")

        description = data.get("description", "")
        _require(
            isinstance(description, str),
            f"dataset {dataset_version}: 'description' must be a string",
        )

        raw_samples = data.get("samples", [])
        _require(
            isinstance(raw_samples, Sequence) and not isinstance(raw_samples, (str, bytes)),
            f"dataset {dataset_version}: 'samples' must be a list",
        )

        unexpected = set(data) - {"dataset_version", "created_on", "description", "samples"}
        _require(
            not unexpected,
            f"dataset {dataset_version}: unexpected manifest keys {sorted(unexpected)}",
        )

        return cls(
            dataset_version=dataset_version,
            created_on=created_on,
            description=description,
            samples=tuple(SampleEntry.from_dict(item) for item in raw_samples),
        )


def supported_keys_only(keys: Sequence[LabelFieldKey]) -> tuple[LabelFieldKey, ...]:
    """`keys` restricted to the declarations the extractor actually attempts.

    `docs/evaluation-strategy.md`: "Report **only the keys the extractor
    actually attempts.** ... including those keys in an aggregate would produce
    a recall figure that is really a measure of how many declarations we chose
    not to implement."

    Annotating an unsupported key is still worth doing - it is the ground truth
    a later implementation is measured against - so this filters at *reporting*
    time rather than rejecting the annotation.
    """
    return tuple(key for key in keys if key in SUPPORTED_KEYS)
