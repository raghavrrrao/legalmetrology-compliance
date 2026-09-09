"""Rule 6(1)(e): a declared retail sale price that contradicts the clause.

The clause as the Department's consolidated publication prints it, with the
words substituted vide G.S.R. 629(E) and further amended vide G.S.R. 779(E) /
G.S.R. 226(E) to give the wording in force from 1 October 2022:

    "the retail sale price of the package; ... shall clearly indicate that it
    is the maximum retail price inclusive of all taxes in Indian currency:"

read with rule 2(m), which defines "retail sale price" as "the maximum price at
which the commodity in packaged form may be sold to the consumer inclusive of
all taxes".

This validator is deliberately narrow, and the narrowness is the point
----------------------------------------------------------------------
The clause has three limbs beyond the price itself: that it is the *maximum*
retail price, that it is *inclusive of all taxes*, and that it is *in Indian
currency*. Only one of them can be decided from a photograph without inventing
a legal test, and only in one direction:

**A price the label declares EXCLUSIVE of all taxes contradicts the clause.**
That is a finding the evidence supports: `labelextract` reads the printed words
"exclusive of all taxes" next to the price and records
`inclusive_of_all_taxes: false`. Nothing about that reading is interpretive.

Everything else is left alone, on purpose:

- **The absence of an "inclusive of all taxes" indication is NOT reported as a
  violation.** Whether printing "MRP" alone "clearly indicates" tax inclusion -
  rule 2(m) defines the term as inclusive - is a question of legal
  construction, and this project's standing rule is that it does not invent
  legal tests. It is recorded in the finding's diagnostics as observed or not
  observed, so a reviewer can see it, and the outcome stays a pass on the
  narrow question asked.
- **"In Indian currency" is NOT checked at all.** `normalise_price` writes
  `currency: "INR"` as a fixed default, not as a reading: it is what the
  normaliser assumes, not what the label was seen to print. Testing the clause
  against it would be testing our own default and reporting the result as
  evidence about the package.
- **Whether the price is the true maximum** is not knowable from a package at
  all. That is rule 18(2), about the price actually charged.

Presence of the price is the separate rule 6(1)(e) presence check; with no
price read, this returns INCONCLUSIVE rather than restating that finding.
"""

from __future__ import annotations

from apps.rules.checks import evidence
from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)

#: The declaration this clause concerns. Fixed rather than a parameter: rule
#: 6(1)(e) is about the retail sale price specifically.
_FIELD = "retail_sale_price"

#: Key `labelextract.fields.normalisation.normalise_price` writes when, and
#: only when, the label printed words the extractor recognised as a tax
#: indication. Absent means "not observed", never "not printed".
_TAX_KEY = "inclusive_of_all_taxes"

_NARROWED_NOTE = (
    "Only one thing is checked here: whether the label declares the price "
    "EXCLUSIVE of all taxes, which contradicts rule 6(1)(e). Whether the price "
    "is clearly indicated as the maximum retail price, whether it is in Indian "
    "currency, and whether it is the true maximum are not checked - the first "
    "is a question of legal construction, the second is assumed by the "
    "normaliser rather than read from the label, and the third is not knowable "
    "from a photograph."
)


def validate_no_parameters(parameters: dict) -> None:
    """This check is fixed to the retail sale price and takes no parameters."""
    if parameters:
        raise InvalidCheckParameters(
            f"retail_price_tax_declaration takes no parameters, got "
            f"{sorted(parameters)}. It is fixed to the {_FIELD!r} declaration, "
            f"because rule 6(1)(e) concerns the retail sale price "
            f"specifically."
        )


def check_retail_price_tax_declaration(
    parameters: dict, context: CheckContext
) -> CheckOutcome:
    """Report whether the declared price contradicts rule 6(1)(e) on taxes."""
    validate_no_parameters(parameters)

    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "Could not check how the retail sale price is declared: no "
                "readable text was extracted from this image. This is not a "
                "finding about the package - try a clearer, closer photograph "
                "of the label."
            ),
            field_key=_FIELD,
            details={"extraction_status": context.run.status},
        )

    reading = context.field(_FIELD)
    if reading is None:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "No retail sale price was read from this label, so how it is "
                "declared could not be examined. Whether a retail sale price "
                "is required at all is the separate rule 6(1)(e) presence "
                "check."
            ),
            field_key=_FIELD,
            details={"extraction_status": context.run.status},
        )

    normalised = reading.normalized_value or {}
    indication = normalised.get(_TAX_KEY)
    details = {
        **evidence.evidence_details(reading),
        "tax_indication_observed": (
            "inclusive"
            if indication is True
            else "exclusive"
            if indication is False
            else "not_observed"
        ),
        "declared_amount": normalised.get("amount"),
        "currency_is_a_normaliser_default_not_a_reading": True,
        "not_checked": [
            "clearly indicated as the maximum retail price",
            "in Indian currency",
            "that the price is the true maximum",
        ],
    }

    if indication is False:
        if not evidence.evidence_supports_a_violation(reading):
            return CheckOutcome(
                status=CheckStatus.INCONCLUSIVE,
                message=(
                    f"The retail sale price appears to be declared exclusive "
                    f"of all taxes, which rule 6(1)(e) does not permit, but "
                    f"the reading is not strong enough to found that finding "
                    f"on. {evidence.insufficient_evidence_note(reading)} "
                    f"{_NARROWED_NOTE}"
                ),
                field_key=_FIELD,
                evidence_excerpt=reading.raw_value,
                bounding_box=reading.bounding_box,
                details=details,
            )
        return CheckOutcome(
            status=CheckStatus.FAILED,
            message=(
                f"The retail sale price is declared EXCLUSIVE of all taxes. "
                f"Rule 6(1)(e) requires the declaration to clearly indicate "
                f"that the price is the maximum retail price inclusive of all "
                f"taxes, and rule 2(m) defines the retail sale price as "
                f"inclusive of all taxes. {_NARROWED_NOTE}"
            ),
            field_key=_FIELD,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    if indication is True:
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                f"The retail sale price is declared inclusive of all taxes, as "
                f"rule 6(1)(e) requires. {_NARROWED_NOTE}"
            ),
            field_key=_FIELD,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    return CheckOutcome(
        status=CheckStatus.PASSED,
        message=(
            f"The retail sale price does not declare itself exclusive of all "
            f"taxes. No wording indicating tax inclusion was read either, "
            f"which is recorded but is NOT treated as a violation: whether "
            f"printing a maximum retail price alone already indicates tax "
            f"inclusion, as rule 2(m) defines it to, is a question of legal "
            f"construction this system does not decide. {_NARROWED_NOTE}"
        ),
        field_key=_FIELD,
        evidence_excerpt=reading.raw_value,
        bounding_box=reading.bounding_box,
        details=details,
    )
