"""Annotation validity: the four states, and what an annotation may not say.

The rules pinned here are the ones that keep ground truth honest. Two matter
more than the rest:

1. **An unreadable declaration may not carry a value.** "The value is illegible,
   and it is 500 g" is a contradiction, and it is the exact shape a pasted OCR
   reading takes when somebody annotates a field they could not actually read.

2. **An un-annotated field reads as UNKNOWN, never as absent.** If absence meant
   NOT_PRESENT, every gap in the annotation effort would score as a false
   positive against the extractor, and precision would *fall* as annotation
   improved.
"""

from __future__ import annotations

import pytest

from labelextract.contracts import LabelFieldKey
from labelextract.evaluation import (
    EvaluationDataError,
    FieldAnnotation,
    FieldTruthState,
    SampleAnnotation,
    supported_keys_only,
)
from labelextract.fields import SUPPORTED_KEYS, UNSUPPORTED_KEYS


def _annotation(**overrides) -> dict:
    payload = {
        "sample_id": "eval_0001",
        "annotated_by": "a-reviewer",
        "annotated_on": "2026-01-15",
        "fields": [],
    }
    payload.update(overrides)
    return payload


# --- the four states ---------------------------------------------------------


def test_all_four_states_are_representable():
    """Collapsing any of these into another makes evaluation ambiguous."""
    assert {state.value for state in FieldTruthState} == {
        "present_and_readable",
        "present_but_unreadable",
        "not_present",
        "unknown",
    }


def test_a_readable_declaration_requires_the_value_the_annotator_read():
    with pytest.raises(EvaluationDataError, match="must carry the value"):
        FieldAnnotation(
            key=LabelFieldKey.NET_QUANTITY,
            state=FieldTruthState.PRESENT_AND_READABLE,
        )


@pytest.mark.parametrize(
    "state",
    [
        FieldTruthState.PRESENT_BUT_UNREADABLE,
        FieldTruthState.NOT_PRESENT,
        FieldTruthState.UNKNOWN,
    ],
)
def test_a_non_readable_state_may_not_carry_a_value(state):
    """The contradiction that a pasted OCR reading produces."""
    with pytest.raises(EvaluationDataError, match="must not carry a value"):
        FieldAnnotation(key=LabelFieldKey.NET_QUANTITY, state=state, value="500 g")


def test_an_unannotated_field_reads_as_unknown_not_absent():
    annotation = SampleAnnotation.from_dict(_annotation())

    field = annotation.field(LabelFieldKey.NET_QUANTITY)
    assert field.state is FieldTruthState.UNKNOWN
    assert field.value is None


def test_an_explicitly_absent_declaration_is_not_unknown():
    """"Not on this panel" is a finding; "not annotated" is an absence of one."""
    annotation = SampleAnnotation.from_dict(
        _annotation(fields=[{"key": "batch_number", "state": "not_present"}])
    )
    assert annotation.field(LabelFieldKey.BATCH_NUMBER).state is (
        FieldTruthState.NOT_PRESENT
    )
    assert annotation.field(LabelFieldKey.NET_QUANTITY).state is FieldTruthState.UNKNOWN


# --- vocabulary --------------------------------------------------------------


def test_an_unknown_field_key_is_refused():
    """The evaluation vocabulary is the extraction vocabulary."""
    with pytest.raises(EvaluationDataError, match="is not a LabelFieldKey"):
        SampleAnnotation.from_dict(
            _annotation(
                fields=[
                    {
                        "key": "nutritional_information",
                        "state": "present_and_readable",
                        "value": "x",
                    }
                ]
            )
        )


def test_every_current_label_field_key_can_be_annotated():
    """Including the unsupported ones: the truth is worth recording now."""
    for key in LabelFieldKey:
        annotation = SampleAnnotation.from_dict(
            _annotation(fields=[{"key": key.value, "state": "not_present"}])
        )
        assert annotation.field(key).state is FieldTruthState.NOT_PRESENT


def test_reporting_is_restricted_to_the_keys_the_extractor_attempts():
    """docs/evaluation-strategy.md: report only the keys actually attempted.

    Including unsupported keys in an aggregate would produce a recall figure
    that really measures how many declarations we chose not to implement.
    """
    reported = supported_keys_only(tuple(LabelFieldKey))

    assert set(reported) == set(SUPPORTED_KEYS)
    assert not set(reported) & set(UNSUPPORTED_KEYS)
    assert UNSUPPORTED_KEYS, "the guard is meaningless if nothing is unsupported"


def test_an_invalid_state_is_refused():
    with pytest.raises(EvaluationDataError, match="not a valid annotation state"):
        SampleAnnotation.from_dict(
            _annotation(fields=[{"key": "net_quantity", "state": "probably_there"}])
        )


# --- provenance --------------------------------------------------------------


def test_an_annotation_without_an_author_is_refused():
    """docs/data-strategy.md: provenance in one person's memory is not provenance."""
    with pytest.raises(EvaluationDataError, match="annotated_by"):
        SampleAnnotation.from_dict(_annotation(annotated_by="   "))


def test_an_annotation_without_a_usable_date_is_refused():
    with pytest.raises(EvaluationDataError, match="annotated_on"):
        SampleAnnotation.from_dict(_annotation(annotated_on="January-ish"))


def test_provenance_survives_parsing():
    annotation = SampleAnnotation.from_dict(_annotation())
    assert annotation.annotated_by == "a-reviewer"
    assert annotation.annotated_on == "2026-01-15"


# --- structural refusals -----------------------------------------------------


def test_two_annotations_for_one_declaration_are_refused():
    """Two answers for one declaration on one photograph cannot both be truth."""
    with pytest.raises(EvaluationDataError, match="annotated more than once"):
        SampleAnnotation.from_dict(
            _annotation(
                fields=[
                    {"key": "net_quantity", "state": "present_and_readable", "value": "500 g"},
                    {"key": "net_quantity", "state": "present_and_readable", "value": "1 kg"},
                ]
            )
        )


def test_an_unexpected_annotation_key_is_refused():
    """A typo in ground truth is invisible once it has become a number."""
    with pytest.raises(EvaluationDataError, match="unexpected annotation keys"):
        SampleAnnotation.from_dict(
            _annotation(
                fields=[
                    {
                        "key": "net_quantity",
                        "state": "present_and_readable",
                        "value": "500 g",
                        "valeu": "typo",
                    }
                ]
            )
        )


def test_an_unexpected_top_level_key_is_refused():
    with pytest.raises(EvaluationDataError, match="unexpected keys"):
        SampleAnnotation.from_dict(_annotation(complaince_status="compliant"))


# --- manifest entry paths ----------------------------------------------------
#
# Tested directly on `SampleEntry` rather than only through `load_dataset`,
# because the loader has a second, independent containment check behind this
# one. That belt-and-braces arrangement is deliberate, but it also means a
# regression here would be invisible from the loader's tests - the second layer
# would quietly cover for the first.


@pytest.mark.parametrize(
    "hostile",
    [
        "../etc/passwd",
        "images/../../escape.png",
        "/absolute/path.png",
        "..\\..\\windows\\system32",
        "images\\..\\escape.png",
    ],
)
def test_a_manifest_entry_path_that_escapes_is_refused(hostile):
    from labelextract.evaluation import SampleEntry

    with pytest.raises(EvaluationDataError):
        SampleEntry(
            sample_id="eval_0001",
            image=hostile,
            annotation="annotations/eval_0001.json",
            image_sha256="0" * 64,
        )


def test_a_backslash_in_a_manifest_path_is_refused_on_its_own():
    """Found in review: the ".." check split on "/" only.

    `..\\..\\windows\\system32` contains no ".." *segment* by that reckoning,
    so it was accepted - and on Windows, where most of this team develops,
    `root / that` really does resolve outside the dataset.
    """
    from labelextract.evaluation import SampleEntry

    with pytest.raises(EvaluationDataError, match="backslash"):
        SampleEntry(
            sample_id="eval_0001",
            image="images\\eval_0001.png",
            annotation="annotations/eval_0001.json",
            image_sha256="0" * 64,
        )


def test_a_relative_posix_manifest_path_is_accepted():
    """The guards must not cost the documented format."""
    from labelextract.evaluation import SampleEntry

    entry = SampleEntry(
        sample_id="eval_0001",
        image="images/eval_0001.png",
        annotation="annotations/eval_0001.json",
        image_sha256="0" * 64,
    )
    assert entry.image == "images/eval_0001.png"


def test_the_schema_records_no_compliance_verdict():
    """This is extraction ground truth. Compliance is the rule engine's job.

    `ml/data/README.md` is explicit that a folder name or filename is never a
    finding, and that a comparison script must take truth from an annotation
    recording who decided. Nothing here may become a back door for a verdict.
    """
    fields = set(SampleAnnotation.__dataclass_fields__)
    for forbidden in ("compliance_status", "result", "verdict", "is_compliant"):
        assert forbidden not in fields


def test_reference_text_is_optional_and_absent_means_absent():
    """CER and WER are unavailable without it - never approximated."""
    assert SampleAnnotation.from_dict(_annotation()).reference_text is None
    with_text = SampleAnnotation.from_dict(_annotation(reference_text="NET QTY 500 g"))
    assert with_text.reference_text == "NET QTY 500 g"


def test_conditions_are_carried_for_per_condition_reporting():
    """docs/evaluation-strategy.md requires reporting per condition, not just a mean."""
    annotation = SampleAnnotation.from_dict(
        _annotation(conditions=["reflective_foil", "low_light"])
    )
    assert annotation.conditions == ("reflective_foil", "low_light")


def test_ground_truth_cannot_be_built_from_an_extraction_result():
    """The types are separate on purpose; there is no bridge between them.

    docs/data-strategy.md requires annotation "independently of the system's
    output", because correcting the system's guesses biases truth toward the
    system. A constructor taking an ExtractionResult is how that rule gets
    broken in a hurry the evening before a deadline.
    """
    for cls in (SampleAnnotation, FieldAnnotation):
        constructors = [name for name in dir(cls) if name.startswith("from_")]
        assert constructors == ["from_dict"], (
            f"{cls.__name__} gained {constructors}; ground truth is parsed from "
            f"files a person wrote, never built from a prediction"
        )
