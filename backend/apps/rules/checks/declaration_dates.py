"""Rule 6(1)(d): does the date declaration actually state a month and a year?

The clause as the Department's consolidated publication prints it:

    "The month and year in which the commodity is manufactured or pre-packed or
    imported shall be mentioned in the package:"

with the annotation that the words "or pre-packed or imported" were omitted
vide G.S.R. 779(E), in force from 1 October 2022 vide G.S.R. 226(E). The
operative clause therefore covers manufacture only, which is why the rule file
that names this validator keys it on `date_of_manufacture` and dates itself
from 2022-10-01.

What this validator asks, and what it deliberately does not
-----------------------------------------------------------
It asks one question: **did the declaration resolve to a month and a year?**

It does **not** validate the printed *format*. The Rules prescribe no format
for this declaration, and rejecting `12/2024` in favour of `DEC 2024`, or the
reverse, would enforce a requirement the source does not contain. Every layout
`labelextract` can resolve is accepted, and every layout it cannot is sent for
review rather than reported as a violation - an unusual printing and a
misrecognised one look identical from here.

The three outcomes
------------------
=======================================  ==================================
normalised reading                       outcome
=======================================  ==================================
`year_month` or `date`, committed to     PASSED - month and year established
uncertain, or neither key present        INCONCLUSIVE
no date declaration read at all          INCONCLUSIVE - presence is the
                                         separate rule 6(1)(d) presence check
=======================================  ==================================

The uncertain branch is the one that earns its place. `03/04/2025` on an Indian
label reads as 3 April or as 4 March, and `labelextract.fields.normalisation`
refuses to choose - it emits both candidates and marks the value uncertain. The
year is settled either way, **the month is not**, so the clause's requirement
is not established and a human has to look. Reporting a pass there would claim
a month this system never determined; reporting a failure would call a
correctly labelled package unlawful because a slash is ambiguous.

There is a second uncertain case with the same answer for a different reason:
the extractor marks a date read from the line *after* its keyword as uncertain,
because nothing but adjacency ties the two together. A month and a year are
legible, but whether they are the *manufacture* date is unestablished.

Parameters:
    field_key (str, required): the date declaration to read, e.g.
        "date_of_manufacture".
"""

from __future__ import annotations

from labelextract.contracts import LabelFieldKey

from apps.rules.checks import evidence
from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)

#: Date declarations this check may be pointed at. Narrower than
#: `LabelFieldKey` on purpose: the question "does this state a month and a
#: year?" is meaningless against a net quantity or a price, and a rule file
#: naming one would be a mistake worth catching at load time rather than a
#: check that silently never matches.
_DATE_KEYS: frozenset[str] = frozenset(
    {
        LabelFieldKey.DATE_OF_MANUFACTURE.value,
        LabelFieldKey.DATE_OF_PACKING.value,
        LabelFieldKey.DATE_OF_IMPORT.value,
        LabelFieldKey.BEST_BEFORE.value,
    }
)

#: Keys `labelextract.fields.normalisation.normalise_date` writes when it has
#: committed to a reading. `date` is a full ISO date, `year_month` a partial
#: one - both carry a month and a year, which is all this clause asks for.
_MONTH_AND_YEAR_KEYS: tuple[str, ...] = ("year_month", "date")


def validate_month_year_parameters(parameters: dict) -> None:
    """Validate the rule's parameters at load time.

    Raises:
        InvalidCheckParameters: naming the offending value.
    """
    field_key = parameters.get("field_key")
    if not field_key or not isinstance(field_key, str):
        raise InvalidCheckParameters(
            "month_year_declaration requires a string 'field_key' parameter"
        )
    if field_key not in _DATE_KEYS:
        raise InvalidCheckParameters(
            f"parameters.field_key must be a date declaration - one of "
            f"{sorted(_DATE_KEYS)} - got {field_key!r}. This check asks "
            f"whether a declaration states a month and a year, which only a "
            f"date declaration can answer."
        )


def check_month_year_declaration(
    parameters: dict, context: CheckContext
) -> CheckOutcome:
    """Report whether the named date declaration establishes a month and year."""
    validate_month_year_parameters(parameters)
    field_key = parameters["field_key"]

    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"Could not check whether '{field_key}' states a month and a "
                f"year: no readable text was extracted from this image. This "
                f"is not a finding about the package - try a clearer, closer "
                f"photograph of the label."
            ),
            field_key=field_key,
            details={"extraction_status": context.run.status},
        )

    reading = context.field(field_key)
    if reading is None:
        # Whether the declaration is required at all is the presence rule's
        # finding. Answering it again here would report one clause twice.
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"No '{field_key}' declaration was read from this label, so "
                f"whether it states a month and a year could not be examined. "
                f"Whether the declaration is required at all is the separate "
                f"presence check on this clause."
            ),
            field_key=field_key,
            details={"extraction_status": context.run.status},
        )

    normalised = reading.normalized_value or {}
    committed = {
        key: normalised[key] for key in _MONTH_AND_YEAR_KEYS if normalised.get(key)
    }
    details = {
        **evidence.evidence_details(reading),
        "month_and_year": committed or None,
        "candidates": list(normalised.get("candidates", [])),
    }

    if committed and not evidence.normalisation_is_uncertain(reading):
        value = committed.get("year_month") or committed.get("date")
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                f"The declaration states a month and a year ({value}). Only "
                f"that is checked: the Rules prescribe no format for this "
                f"declaration, and whether the date is TRUE cannot be "
                f"established from a photograph."
            ),
            field_key=field_key,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    candidates = normalised.get("candidates") or []
    ambiguity = (
        f" The readings that could not be chosen between are "
        f"{', '.join(str(candidate) for candidate in candidates)}."
        if candidates
        else ""
    )
    # Empty whenever the reading itself was sound and simply did not answer the
    # question - a shelf life expressed as a duration, say. Asserting a
    # confidence problem there would be false.
    quality = evidence.insufficient_evidence_note(reading)
    return CheckOutcome(
        status=CheckStatus.INCONCLUSIVE,
        message=(
            f"A '{field_key}' declaration was read from this label, but a "
            f"month and a year could not be established from it, so no "
            f"conclusion has been drawn about the clause."
            f"{ambiguity}"
            f"{' ' + quality if quality else ''} This is not a "
            f"finding that the declaration is wrong - an unusual printing and "
            f"a misrecognised one look the same from here, and the Rules "
            f"prescribe no format to measure it against."
        ),
        field_key=field_key,
        evidence_excerpt=reading.raw_value,
        bounding_box=reading.bounding_box,
        details=details,
    )
