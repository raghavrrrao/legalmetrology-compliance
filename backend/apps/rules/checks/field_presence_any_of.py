"""The `field_presence_any_of` validator: was at least one of these declared?

Like `field_presence`, this contains no legal content. It answers a mechanical
question - "did any of these declarations appear?" - and the rule row supplies
the claim that one of them is required.

Why a separate check rather than a parameter on `field_presence`
----------------------------------------------------------------
Because the two answer different questions and their failure messages differ.
`field_presence` failing means "this declaration is absent". This failing means
"none of these alternatives is present", and a user reading it needs to be told
what *would* have satisfied the requirement.

What it unblocks
----------------
Rule 6(1)(a) is disjunctive: a package satisfies it by declaring the
manufacturer, or the manufacturer and the packer, or - for an imported package
- the importer. `rules/INVENTORY.md` records that `LM-PC-0001` shipped inactive
precisely because `field_presence` tests exactly one key, so a rule keyed on
`manufacturer_name` would report a lawfully labelled imported package, which
declares only `importer_name`, as NON_COMPLIANT.

What it deliberately does NOT do
--------------------------------
It does not check the *address*. `manufacturer_address` is in the extractor's
`UNSUPPORTED_KEYS`, so its absence carries no information, and rule 10(1) is the
operative provision for address completeness. A check that quietly ignored the
address half while reporting on the clause as a whole would over-claim; the
rule's own requirement text says what is and is not covered.

Parameters:
    field_keys (list[str], required): two or more `LabelFieldKey` values.
"""

from __future__ import annotations

from labelextract.contracts import LabelFieldKey

from apps.rules.checks.base import (
    CheckContext,
    CheckOutcome,
    CheckStatus,
    InvalidCheckParameters,
)


def validate_field_presence_any_of_parameters(parameters: dict) -> None:
    """Validate the rule's parameters at load time.

    Requires at least two keys. One key is not a disjunction, and expressing it
    this way would hide a plain `field_presence` rule behind a check whose
    failure message talks about alternatives that do not exist.

    Raises:
        InvalidCheckParameters: with a message naming the offending value.
    """
    field_keys = parameters.get("field_keys")
    if not isinstance(field_keys, list) or not field_keys:
        raise InvalidCheckParameters(
            "field_presence_any_of requires a non-empty 'field_keys' list"
        )
    if len(field_keys) < 2:
        raise InvalidCheckParameters(
            "field_presence_any_of requires at least two keys in 'field_keys'; "
            "use check_type 'field_presence' for a single declaration"
        )

    valid_keys = [key.value for key in LabelFieldKey]
    for field_key in field_keys:
        if not isinstance(field_key, str) or field_key not in valid_keys:
            raise InvalidCheckParameters(
                f"every entry in parameters.field_keys must be one of "
                f"{valid_keys}, got {field_key!r}"
            )

    if len(set(field_keys)) != len(field_keys):
        raise InvalidCheckParameters(
            "parameters.field_keys contains a duplicate; each alternative must "
            "appear once"
        )


def check_field_presence_any_of(
    parameters: dict, context: CheckContext
) -> CheckOutcome:
    """Report whether any of `parameters['field_keys']` was read from the label."""
    field_keys = parameters.get("field_keys")
    if not isinstance(field_keys, list) or len(field_keys) < 2:
        # A configuration error, not a compliance finding.
        raise InvalidCheckParameters(
            "field_presence_any_of requires a 'field_keys' list of at least two "
            "LabelFieldKey values"
        )

    found = [(key, context.field(key)) for key in field_keys]
    present = [(key, value) for key, value in found if value is not None]

    if present:
        # Reported against the first alternative that was found, so the finding
        # points at a reading that actually exists. The rest are named in the
        # message, because which alternative satisfied the clause is exactly
        # what a reviewer checking a disjunctive requirement needs to see.
        key, value = present[0]
        satisfied = ", ".join(sorted(k for k, _ in present))
        return CheckOutcome(
            status=CheckStatus.PASSED,
            message=(
                f"The requirement is satisfied by {satisfied}, which "
                f"{'was' if len(present) == 1 else 'were'} found on the label. "
                f"Any one of {', '.join(field_keys)} satisfies it."
            ),
            field_key=key,
            evidence_excerpt=value.raw_value,
            bounding_box=value.bounding_box,
            details={
                "satisfied_by": sorted(k for k, _ in present),
                "alternatives": list(field_keys),
                "confidence": value.confidence,
            },
        )

    if not context.extraction_was_usable:
        return CheckOutcome(
            status=CheckStatus.INCONCLUSIVE,
            message=(
                f"Could not determine whether any of "
                f"{', '.join(field_keys)} is declared: no readable text was "
                f"extracted from this image. This is not a finding about the "
                f"package - try a clearer, closer photograph of the label."
            ),
            field_key=field_keys[0],
            details={
                "alternatives": list(field_keys),
                "extraction_status": context.run.status,
                "extraction_error_code": context.run.error_code or None,
                "is_placeholder_engine": context.run.is_placeholder,
            },
        )

    return CheckOutcome(
        status=CheckStatus.FAILED,
        message=(
            f"None of {', '.join(field_keys)} was found in the text read from "
            f"this image. Any one of them would satisfy this requirement."
        ),
        field_key=field_keys[0],
        evidence_excerpt=_excerpt(context.run.recognised_text),
        details={
            "alternatives": list(field_keys),
            "extraction_status": context.run.status,
        },
    )


#: Matches `field_presence._EXCERPT_LIMIT`. Kept as its own constant rather than
#: imported, so tuning one check's evidence length does not silently retune the
#: other's.
_EXCERPT_LIMIT = 500


def _excerpt(text: str) -> str:
    if len(text) <= _EXCERPT_LIMIT:
        return text
    return text[:_EXCERPT_LIMIT] + "..."
