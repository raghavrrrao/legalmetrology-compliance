"""The `field_presence` validator: was this declaration found on the label?

This is a purely mechanical question. It contains no legal content whatsoever -
it does not know or care whether the declaration is required. The rule row that
names this validator supplies that claim, sourced from verified legal material.

Parameters:
    field_key (str, required): a `LabelFieldKey` value, e.g. "net_quantity".

Three statuses, reached by four routes:

    field found                            -> PASSED
    field absent, extraction not usable    -> INCONCLUSIVE
    field absent, but the label named it   -> INCONCLUSIVE
    field absent, extraction was usable    -> FAILED

INCONCLUSIVE is the whole reason this returns three values, and it is reached
two different ways.

The first is a blurred, dark or badly framed photograph, which produces no
declarations at all. Reporting that as FAILED would tell a user their product
is non-compliant when the only thing we actually established is that we could
not read their photo.

The second is narrower and was, until this check was extended, reported as a
violation. A photograph of a curved can catches the declaration panel edge-on
and OCR returns the single line `MRP` - the keyword, legibly, with nothing
after it. The extraction is perfectly usable overall; other declarations were
read from the same image. But for *this* declaration the label plainly says one
thing and we cannot say what. `CheckContext.unread(field_key)` is how the ML
layer reports that, and the difference it settles is:

    the package declares no MRP          -> a potential violation
    the MRP is printed and unreadable    -> re-photograph that panel

Those are opposite findings, and an absent `ExtractedLabelField` says both.

An unread declaration can therefore *stop* a FAILED, and can never produce a
PASSED. It carries no value - the schema will not hold one - so there is
nothing for a presence check to be satisfied by.
"""

from __future__ import annotations

from labelextract.contracts import LabelFieldKey

from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)


def validate_field_presence_parameters(parameters: dict) -> None:
    """Validate a `field_presence` rule's parameters at load time.

    Registered alongside the validator, so the rule loader rejects a bad rule
    file before it can be attached to a real product's compliance result.

    `field_key` must be a member of the extraction vocabulary. Checking it here
    is what stops a typo like "net_qty" from producing a rule that silently
    never matches anything - which would look exactly like a compliant product.

    Raises:
        InvalidCheckParameters: with a message naming the offending key.
    """
    field_key = parameters.get("field_key")
    if not field_key or not isinstance(field_key, str):
        raise InvalidCheckParameters(
            "field_presence requires a string 'field_key' parameter"
        )

    valid_keys = [key.value for key in LabelFieldKey]
    if field_key not in valid_keys:
        raise InvalidCheckParameters(
            f"parameters.field_key must be one of {valid_keys}, "
            f"got {field_key!r}"
        )


def check_field_presence(parameters: dict, context: CheckContext) -> CheckOutcome:
    """Report whether the declaration named by `parameters['field_key']` was read."""
    field_key = parameters.get("field_key")
    if not field_key or not isinstance(field_key, str):
        # A configuration error, not a compliance finding. Raised rather than
        # returned so a malformed rule is loud instead of quietly passing.
        raise InvalidCheckParameters(
            "field_presence requires a string 'field_key' parameter"
        )

    found = context.field(field_key)

    if found is not None:
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=f"Declaration '{field_key}' was found on the label.",
            field_key=field_key,
            evidence_excerpt=found.raw_value,
            bounding_box=found.bounding_box,
            details={"confidence": found.confidence},
        )

    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"Could not determine whether '{field_key}' is declared: no "
                f"readable text was extracted from this image. This is not a "
                f"finding about the package - try a clearer, closer photograph "
                f"of the label."
            ),
            field_key=field_key,
            details={
                "extraction_status": context.run.status,
                "extraction_error_code": context.run.error_code or None,
                "is_placeholder_engine": context.run.is_placeholder,
            },
        )

    unread = context.unread(field_key)
    if unread is not None:
        # The label names this declaration and its value was not legible. That
        # is not evidence of absence, and it is checked before the FAILED
        # branch precisely so it cannot become one.
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"Could not determine whether '{field_key}' is correctly "
                f"declared: the label names this declaration but its value "
                f"could not be read from this image. This is not a finding "
                f"that the declaration is missing - try a clearer, straighter "
                f"photograph of that panel."
            ),
            field_key=field_key,
            # The line the keyword was read on, so a reviewer can see the
            # declaration is there and judge the photograph for themselves.
            evidence_excerpt=unread.evidence_text,
            bounding_box=unread.bounding_box,
            details={
                "extraction_status": context.run.status,
                "declaration_named_but_unread": True,
                "evidence_confidence": unread.confidence,
            },
        )

    return CheckOutcome(
        status=CheckStatus.FAILED,
        message=(
            f"Declaration '{field_key}' was not found in the text read from "
            f"this image."
        ),
        field_key=field_key,
        evidence_excerpt=_excerpt(context.run.recognised_text),
        details={"extraction_status": context.run.status},
    )


#: How much recognised text to attach as evidence for an absence. Enough to
#: show the user what we did read, short enough not to bloat every violation.
_EXCERPT_LIMIT = 500


def _excerpt(text: str) -> str:
    if len(text) <= _EXCERPT_LIMIT:
        return text
    return text[:_EXCERPT_LIMIT] + "..."
