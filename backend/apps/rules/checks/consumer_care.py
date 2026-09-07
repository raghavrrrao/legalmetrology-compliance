"""Rule 6(2): which elements of the consumer-care declaration are present.

The clause, verbatim from the Department of Consumer Affairs consolidated
publication recorded in `rules/SOURCES.md`, as substituted vide G.S.R. 385(E)
with effect from 1 January 2016:

    "Every package shall bear the name, address, telephone number, e-mail
    address of the person who can be or the office which can be contacted, in
    case of consumer complaints."

Four elements. This validator can test **two** of them, and says so in every
outcome it produces.

What is tested, and what is not
-------------------------------
========================  ============================================
element                   status here
========================  ============================================
telephone number          tested - `normalized_value["phones"]`
e-mail address            tested - `normalized_value["emails"]`
name of the person/office NOT tested - no extraction field exists
address                   NOT tested - `manufacturer_address` is in the
                          extractor's UNSUPPORTED_KEYS, and rule 10(1) is
                          the operative address provision
========================  ============================================

So a PASSED outcome here means "the two elements this system can verify were
found", never "the package complies with rule 6(2)". The message says that in
words, because a finding is read on its own.

Why this is a separate rule from the presence check
---------------------------------------------------
`LM-PC-0006` asks whether a consumer-care declaration was read at all; this
asks what it contained. `ComplianceRule.rule_requirement` is deliberately
many-rules-to-one-clause for exactly this ("presence and format are separate
checks of one clause"), and keeping them apart means a package that declares a
phone but no e-mail produces one precise finding about the e-mail rather than a
second, vaguer copy of the presence finding.

It also means this validator never duplicates the presence verdict: with no
consumer-care declaration read at all, it returns INCONCLUSIVE and points at
the presence rule, in the same way the rule 13 validators defer the question of
whether a net quantity is required at all to rule 6(1)(c).

Why absence of an element can be a violation at all
---------------------------------------------------
Because of what `emails` and `phones` mean after `labelextract`'s consumer-care
detector merges its per-line readings: they are **every** e-mail and telephone
token recognised anywhere in the label text, not only those on one line. An
empty `emails` list therefore says "no e-mail address was recognised on this
label", which is a real negative rather than an artefact of which line won.

It is still a reading, so `evidence.evidence_supports_a_violation` gates it:
an uncertain interpretation or a low reported confidence yields INCONCLUSIVE.
"""

from __future__ import annotations

from apps.rules.checks import evidence
from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)

#: The declaration this clause concerns. Fixed rather than a parameter, for the
#: same reason rule 13's validators fix themselves to the net quantity: rule
#: 6(2) is about the consumer-care contact specifically, and pointing this at
#: another declaration would ask a question the clause does not ask.
_FIELD = "consumer_care_contact"

#: The elements of the clause this validator can test, and the key in
#: `normalized_value` that evidences each. Ordered as the clause lists them.
_TESTABLE_ELEMENTS: tuple[tuple[str, str], ...] = (
    ("telephone number", "phones"),
    ("e-mail address", "emails"),
)

#: The elements of the clause this validator cannot test. Named in every
#: outcome so a pass cannot be read as covering them.
_UNTESTABLE_ELEMENTS: tuple[str, ...] = (
    "name of the person or office to be contacted",
    "address of the person or office to be contacted",
)

_UNTESTED_NOTE = (
    "Rule 6(2) also requires the name and the address of the person or office "
    "to be contacted. Neither is checked here: the extractor reads no "
    "consumer-care name, and addresses are not extracted at all - rule 10(1) "
    "is the operative address provision. This outcome covers the telephone "
    "number and the e-mail address only."
)


def validate_no_parameters(parameters: dict) -> None:
    """This check is fixed to the consumer-care declaration and takes none."""
    if parameters:
        raise InvalidCheckParameters(
            f"consumer_care_elements takes no parameters, got "
            f"{sorted(parameters)}. It is fixed to the {_FIELD!r} declaration, "
            f"because rule 6(2) concerns the consumer-care contact "
            f"specifically."
        )


def check_consumer_care_elements(
    parameters: dict, context: CheckContext
) -> CheckOutcome:
    """Report which elements of the consumer-care declaration were read."""
    validate_no_parameters(parameters)

    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "Could not check the elements of the consumer-care "
                "declaration: no readable text was extracted from this image. "
                "This is not a finding about the package - try a clearer, "
                "closer photograph of the label."
            ),
            field_key=_FIELD,
            details={"extraction_status": context.run.status},
        )

    reading = context.field(_FIELD)
    if reading is None:
        # Whether a consumer-care declaration is required at all is the
        # presence rule's finding. Repeating it here would report one clause
        # twice and would make a package that declares nothing look worse than
        # one that declares half of what it owes.
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "No consumer-care declaration was read from this label, so "
                "which of its elements are present could not be examined. "
                "Whether the declaration is required at all is the separate "
                "rule 6(2) presence check."
            ),
            field_key=_FIELD,
            details={"extraction_status": context.run.status},
        )

    normalised = reading.normalized_value or {}
    present = [
        (element, key) for element, key in _TESTABLE_ELEMENTS if normalised.get(key)
    ]
    missing = [
        (element, key)
        for element, key in _TESTABLE_ELEMENTS
        if not normalised.get(key)
    ]
    details = {
        **evidence.evidence_details(reading),
        "elements_found": {key: list(normalised.get(key) or []) for _, key in present},
        "elements_not_found": [element for element, _ in missing],
        "elements_not_checked": list(_UNTESTABLE_ELEMENTS),
    }

    if not present:
        # A consumer-care declaration was located - the keyword is on the label
        # - but nothing readable came out of it. That is a photograph problem,
        # not a package problem.
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                "A consumer-care declaration was found on the label, but "
                "neither a telephone number nor an e-mail address could be "
                "read from it, so no conclusion has been drawn about the "
                f"elements rule 6(2) requires. {_UNTESTED_NOTE}"
            ),
            field_key=_FIELD,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    if not missing:
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                "The consumer-care declaration states both a telephone number "
                "and an e-mail address. "
                f"{_UNTESTED_NOTE} This is not a finding that the package "
                "complies with rule 6(2) as a whole."
            ),
            field_key=_FIELD,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    named_missing = " and ".join(element for element, _ in missing)
    named_present = " and ".join(element for element, _ in present)

    if not evidence.evidence_supports_a_violation(reading):
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"A consumer-care {named_present} was read from this label but "
                f"no {named_missing}. "
                f"{evidence.insufficient_evidence_note(reading)} Rule 6(2) "
                f"requires both. {_UNTESTED_NOTE}"
            ),
            field_key=_FIELD,
            evidence_excerpt=reading.raw_value,
            bounding_box=reading.bounding_box,
            details=details,
        )

    return CheckOutcome(
        status=CheckStatus.FAILED,
        message=(
            f"The consumer-care {named_missing} required by rule 6(2) was not "
            f"found anywhere in the text read from this label. A consumer-care "
            f"{named_present} was read. Rule 6(2) requires the name, address, "
            f"telephone number and e-mail address of the person or office to "
            f"be contacted in case of consumer complaints. {_UNTESTED_NOTE}"
        ),
        field_key=_FIELD,
        evidence_excerpt=reading.raw_value,
        bounding_box=reading.bounding_box,
        details=details,
    )
