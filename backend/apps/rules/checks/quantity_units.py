"""Validators for how a net quantity is expressed: rules 13(4) and 13(5).

Both clauses are transcribed verbatim in `rules/framework/rules.json`, both are
purely textual, and both need no applicability input beyond the declared value
itself - which is why `rules/INVENTORY.md` names rule 13 the strongest
candidate for the next real rule after a format check exists.

These read the **normalised** reading first and fall back to the raw string,
rather than re-parsing OCR text. `labelextract` already decided what the unit
was; re-deriving it here would give two answers that can disagree.

The distinction these validators are built around
-------------------------------------------------
The normaliser recognises SI mass and volume units and count units, and nothing
else. So an unrecognised unit is **not** evidence of a non-SI declaration - it
is evidence that we could not interpret the reading, and `oz` misread from a
smudged `g` looks identical to a genuine ounce. Reporting that as a rule 13(5)
violation would turn an OCR defect into a legal finding.

So there are three outcomes, not two: a unit known to be SI passes, a unit
known not to be SI fails, and a unit we cannot place is INCONCLUSIVE. Only the
middle case is a violation, and the list backing it is short and consists of
units whose non-SI status is a matter of fact rather than interpretation.
"""

from __future__ import annotations

import re

from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)

#: The declaration both clauses concern. Fixed rather than a parameter: rule
#: 13 is about the net quantity specifically, and pointing these at another
#: field would ask a question neither clause asks.
_NET_QUANTITY = "net_quantity"

#: SI unit spellings the extractor can emit as `normalized_value["unit"]`.
#:
#: Restated here rather than imported from `labelextract.fields.normalisation`,
#: which holds the same sets. That is not duplication for its own sake: the
#: backend enforces a hard boundary that only
#: `apps/extraction/services/extraction_service.py` may reach the ML runtime
#: (see `test_no_backend_module_outside_extraction_imports_an_engine`), and it
#: is a boundary worth keeping - a rules module importing an extractor's
#: internals pins the legal layer to one implementation.
#:
#: The cost is that the two lists can drift, so they are not left to trust:
#: `apps/rules/tests/test_quantity_units.py` imports both and asserts they
#: agree, and fails the moment either side learns a spelling the other has not.
_SI_MASS_UNITS: frozenset[str] = frozenset(
    {
        "mcg", "ug", "mg", "g", "gm", "gms", "gram", "grams", "gr",
        "kg", "kgs", "kilogram", "kilograms",
    }
)
_SI_VOLUME_UNITS: frozenset[str] = frozenset(
    {
        "ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters",
        "cc", "cl", "dl", "l", "ltr", "ltrs", "lt",
        "litre", "litres", "liter", "liters",
    }
)
_SI_UNITS: frozenset[str] = _SI_MASS_UNITS | _SI_VOLUME_UNITS

#: Units of number. Rule 13(5)(ii) provides for items sold by number, so these
#: do not engage the prohibition on non-SI systems of units.
_COUNT_UNITS: frozenset[str] = frozenset(
    {"n", "u", "pc", "pcs", "piece", "pieces", "no", "nos", "unit", "units"}
)


def _is_uncertain(normalised: dict | None) -> bool:
    """Whether the normaliser refused to commit to an interpretation.

    Mirrors `labelextract.fields.normalisation.is_uncertain` across the same
    boundary as the unit sets above. Recorded in diagnostics only - nothing
    here conditions an outcome on it, because uncertainty of interpretation is
    a different axis from whether the declared unit is lawful.
    """
    return bool((normalised or {}).get("uncertain"))

#: Units whose non-SI status is a plain fact, not a legal judgement. Kept
#: deliberately short: everything here is an imperial or US customary unit of
#: mass or volume with no SI reading. Anything NOT on this list and not
#: recognised is inconclusive, never a violation.
_KNOWN_NON_SI: dict[str, str] = {
    "oz": "ounce",
    "ozs": "ounce",
    "ounce": "ounce",
    "ounces": "ounce",
    "lb": "pound",
    "lbs": "pound",
    "pound": "pound",
    "pounds": "pound",
    "fl oz": "fluid ounce",
    "floz": "fluid ounce",
    "pt": "pint",
    "pint": "pint",
    "pints": "pint",
    "qt": "quart",
    "quart": "quart",
    "quarts": "quart",
    "gal": "gallon",
    "gallon": "gallon",
    "gallons": "gallon",
    "grain": "grain",
    "grains": "grain",
}

#: The counting units rule 13(4) names, verbatim: "No number called the dozen,
#: score, gross, great gross or the like shall be specified or indicated on any
#: package." Only the named words are matched. "or the like" is open-ended and
#: no list can close it, which is why a pass here is reported as covering the
#: named units only.
_PROHIBITED_COUNTING_UNITS: tuple[str, ...] = (
    "great gross",
    "dozen",
    "dozens",
    "score",
    "scores",
    "gross",
)

#: `gross` also occurs in "gross weight", which is an ordinary and lawful
#: phrase on a package. Matching it there would report a violation against a
#: correctly labelled product, so the word is not treated as a counting unit
#: when it qualifies a weight or a mass.
_GROSS_AS_WEIGHT = re.compile(r"\bgross\s+(weight|wt|mass|vol|volume)\b", re.I)


def validate_no_parameters(parameters: dict) -> None:
    """Both checks are fixed to the net-quantity declaration and take none."""
    if parameters:
        raise InvalidCheckParameters(
            f"this check takes no parameters, got {sorted(parameters)}. It is "
            f"fixed to the '{_NET_QUANTITY}' declaration, because rule 13 "
            f"concerns the net quantity specifically."
        )


def _unreadable(context: CheckContext, clause: str) -> CheckOutcome | None:
    """Return an INCONCLUSIVE outcome when there is nothing to judge.

    Absence of the declaration is rule 6(1)(c)'s finding, not rule 13's. Rule
    13 governs *how* a quantity is expressed, so with no quantity read there is
    nothing for it to say - and saying "passed" would be reporting compliance
    with a manner-of-declaration rule on a package that may declare nothing at
    all.
    """
    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"Could not check {clause}: no readable text was extracted "
                f"from this image. This is not a finding about the package - "
                f"try a clearer, closer photograph of the label."
            ),
            field_key=_NET_QUANTITY,
            details={"extraction_status": context.run.status},
        )

    if context.field(_NET_QUANTITY) is None:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"No net quantity declaration was read from this label, so "
                f"{clause}, which governs how a quantity is expressed, could "
                f"not be applied. Whether a net quantity is required at all is "
                f"rule 6(1)(c)."
            ),
            field_key=_NET_QUANTITY,
            details={"extraction_status": context.run.status},
        )
    return None


# ---------------------------------------------------------------------------
# Rule 13(5) - International System of Units
# ---------------------------------------------------------------------------


def check_si_unit(parameters: dict, context: CheckContext) -> CheckOutcome:
    """Is the net quantity expressed in SI units, or in units sold by number?"""
    validate_no_parameters(parameters)

    unreadable = _unreadable(context, "rule 13(5)")
    if unreadable is not None:
        return unreadable

    reading = context.field(_NET_QUANTITY)
    normalised = reading.normalized_value or {}
    unit = (normalised.get("unit") or "").strip().lower()

    if not unit:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "The net quantity declaration was read but no unit could be "
                "identified in it, so whether SI units were used could not be "
                "determined."
            ),
            field_key=_NET_QUANTITY,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details={
                "normalised": normalised,
                "confidence": reading.confidence,
            },
        )

    if unit in _KNOWN_NON_SI:
        return CheckOutcome(
            status=CheckStatus.FAILED,
            message=(
                f"The net quantity is declared in {_KNOWN_NON_SI[unit]}s "
                f"({unit!r}), which is not a unit of the International System "
                f"of Units. Rule 13(5) permits no system of units other than "
                f"the International System of Units for the net quantity."
            ),
            field_key=_NET_QUANTITY,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details={
                "declared_unit": unit,
                "unit_family": _KNOWN_NON_SI[unit],
                "confidence": reading.confidence,
            },
        )

    if unit in _SI_UNITS:
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                f"The net quantity is declared in {unit!r}, a unit of the "
                f"International System of Units."
            ),
            field_key=_NET_QUANTITY,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details={"declared_unit": unit, "confidence": reading.confidence},
        )

    if unit in _COUNT_UNITS:
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                f"The commodity is declared by number ({unit!r}). Rule "
                f"13(5)(ii) provides for items sold by number, so the "
                f"prohibition on non-SI systems of units is not engaged."
            ),
            field_key=_NET_QUANTITY,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details={"declared_unit": unit, "confidence": reading.confidence},
        )

    # The load-bearing branch. An unplaceable unit is a reading we could not
    # interpret, not a declaration we found unlawful: `oz` misread from a
    # smudged `g` is indistinguishable here from a genuine ounce.
    return CheckOutcome(
        status=CheckStatus.INCONCLUSIVE,
        message=(
            f"The unit {unit!r} in the net quantity declaration could not be "
            f"identified as an SI unit, a unit of number, or a known non-SI "
            f"unit. This is not a finding that the declaration is unlawful - "
            f"an unreadable or unusual unit looks the same here as a "
            f"misrecognised one, and it needs a human to look at the label."
        ),
        field_key=_NET_QUANTITY,
        evidence_excerpt=reading.raw_value,
        bounding_box=reading.bounding_box,
        details={
            "declared_unit": unit,
            "normalisation_uncertain": _is_uncertain(normalised),
            "uncertainty_reasons": normalised.get("uncertainty_reasons", []),
            "confidence": reading.confidence,
        },
    )


# ---------------------------------------------------------------------------
# Rule 13(4) - dozen, score, gross, great gross
# ---------------------------------------------------------------------------


def check_prohibited_counting_unit(
    parameters: dict, context: CheckContext
) -> CheckOutcome:
    """Does the net quantity use a counting unit rule 13(4) prohibits?"""
    validate_no_parameters(parameters)

    unreadable = _unreadable(context, "rule 13(4)")
    if unreadable is not None:
        return unreadable

    reading = context.field(_NET_QUANTITY)
    # The declaration only, not the whole recognised text. Rule 13(4) reaches
    # anything "specified or indicated on any package", but scanning every line
    # would match "Gross Weight" and other lawful prose, and a false violation
    # is worse than an under-claim. The message records the narrowing.
    haystack = f"{reading.raw_value} {(reading.normalized_value or {}).get('unit', '')}"
    masked = _GROSS_AS_WEIGHT.sub(" ", haystack)

    for prohibited in _PROHIBITED_COUNTING_UNITS:
        if re.search(rf"\b{re.escape(prohibited)}\b", masked, re.I):
            return CheckOutcome(
                status=CheckStatus.FAILED,
                message=(
                    f"The net quantity declaration uses {prohibited!r}. Rule "
                    f"13(4) provides that no number called the dozen, score, "
                    f"gross, great gross or the like shall be specified or "
                    f"indicated on any package."
                ),
                field_key=_NET_QUANTITY,
                evidence_excerpt=reading.raw_value,
                bounding_box=reading.bounding_box,
                details={
                    "matched_term": prohibited,
                    "confidence": reading.confidence,
                },
            )

    return CheckOutcome(
        status=CheckStatus.PASSED,
        message=(
            "The net quantity declaration does not use dozen, score, gross or "
            "great gross. Note that rule 13(4) also prohibits units 'or the "
            "like', which is open-ended: only the units the clause names were "
            "checked, and only within the net quantity declaration itself."
        ),
        field_key=_NET_QUANTITY,
        evidence_excerpt=reading.raw_value,
        bounding_box=reading.bounding_box,
        details={
            "checked_terms": list(_PROHIBITED_COUNTING_UNITS),
            "scope": "net_quantity declaration only",
            "confidence": reading.confidence,
        },
    )
