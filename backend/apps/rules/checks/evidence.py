"""When the evidence behind a reading is strong enough to fail a package.

Every validator in this package answers a factual question. Three of them -
`consumer_care_elements`, `month_year_declaration` and
`retail_price_tax_declaration` - go a step further than presence and read the
*normalised interpretation* of a declaration to decide whether the clause is
met. That extra step is where a bad photograph can turn into a legal finding,
so the guards it needs are collected here rather than restated three times.

Two signals, and they are different axes
----------------------------------------
**Interpretation.** `normalized_value["uncertain"]` is the extractor's own
statement that it could not commit to a reading - an ambiguous `03/04/2025`, a
price with no keyword to anchor it, a unit it could not place. It is set by
`labelextract.fields.normalisation` and is documented there as being about
*meaning*.

**Recognition.** `ExtractedLabelField.confidence` is the OCR engine's opinion of
the *characters*, in [0, 1], or NULL when the engine does not report one. A
perfectly recognised ambiguous date is high-confidence and uncertain at once.

A validator here may report FAILED only when neither signal is against it.
Where either is, the outcome is INCONCLUSIVE - which the engine records as
review, never as a violation.

Why the threshold below is a defensible number to pick
------------------------------------------------------
It is **not** derived from the Rules, and nothing in the Rules speaks to OCR
confidence. It is an engineering threshold, and the property that makes it safe
to choose without measuring is directional: **lowering the bar for evidence can
only move an outcome from FAILED to INCONCLUSIVE, never the other way.** A
badly chosen value costs recall - some real violations reach a human instead of
being reported - and can never manufacture a violation that the evidence does
not support. That is the direction this project errs in everywhere else.

NULL confidence is treated as *unknown*, not as low, matching
`ExtractedLabelField.confidence`'s own documentation that NULL "must never be
treated as zero or as certainty". Blocking on NULL would disable these checks
entirely for any engine that reports no confidence. The finding records that no
confidence was reported, so a reviewer can see which it was.

These constants restate nothing from `labelextract`; the uncertainty *key* is
part of the persisted `normalized_value` contract, which the backend reads
directly. Nothing here imports the ML runtime - see
`test_no_backend_module_outside_extraction_imports_an_engine`.
"""

from __future__ import annotations

from apps.extraction.models import ExtractedLabelField

#: Key `labelextract.fields.normalisation` writes onto every mapping it
#: produces. Restated rather than imported, across the same boundary as the
#: unit sets in `quantity_units`.
UNCERTAIN_KEY = "uncertain"
REASONS_KEY = "uncertainty_reasons"

#: Below this, a reading is not strong enough to found a violation on. See the
#: module docstring for why picking a number here is safe.
LOW_CONFIDENCE_THRESHOLD = 0.5


def normalisation_is_uncertain(field: ExtractedLabelField | None) -> bool:
    """Whether the extractor declined to commit to an interpretation.

    A field with no `normalized_value` counts as uncertain: no normaliser ran,
    so nothing has vouched for a reading, and a check that needs the structured
    value has nothing to work from. Mirrors
    `labelextract.fields.normalisation.is_uncertain`, whose default is the same
    and for the same reason.
    """
    if field is None:
        return True
    normalised = field.normalized_value
    if not normalised:
        return True
    return bool(normalised.get(UNCERTAIN_KEY, True))


def confidence_is_low(field: ExtractedLabelField | None) -> bool:
    """Whether the engine reported a confidence and it was below the threshold.

    False when no confidence was reported. That is "unknown", not "low", and
    the caller records the distinction in its diagnostics.
    """
    if field is None or field.confidence is None:
        return False
    return float(field.confidence) < LOW_CONFIDENCE_THRESHOLD


def evidence_supports_a_violation(field: ExtractedLabelField | None) -> bool:
    """Whether a negative conclusion may be drawn from this reading.

    The one gate the three interpreting validators share. Both signals must be
    clear: the extractor committed to an interpretation, and the engine did not
    report a low confidence in the characters.
    """
    return not normalisation_is_uncertain(field) and not confidence_is_low(field)


def evidence_details(field: ExtractedLabelField | None) -> dict:
    """The diagnostics every interpreting validator attaches to its outcome.

    Written whatever the outcome, so a reviewer reading a PASSED finding can
    see the same evidence quality a FAILED one would have been judged on.
    """
    if field is None:
        return {"confidence": None, "normalisation_uncertain": True}
    normalised = field.normalized_value or {}
    return {
        "confidence": field.confidence,
        "confidence_reported": field.confidence is not None,
        "confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "normalisation_uncertain": normalisation_is_uncertain(field),
        "uncertainty_reasons": list(normalised.get(REASONS_KEY, [])),
    }


def insufficient_evidence_note(field: ExtractedLabelField | None) -> str:
    """A sentence naming which signal withheld a verdict, for the message.

    Empty when neither signal is against the reading. A caller may be
    inconclusive for a reason that has nothing to do with evidence quality -
    a committed, high-confidence reading that simply does not answer the
    question - and asserting a confidence problem there would be false.
    """
    if evidence_supports_a_violation(field):
        return ""
    if normalisation_is_uncertain(field):
        reasons = (field.normalized_value or {}).get(REASONS_KEY, []) if field else []
        detail = f" ({'; '.join(reasons)})" if reasons else ""
        return (
            f"The reading could not be interpreted with confidence{detail}, so "
            f"no conclusion has been drawn from it."
        )
    return (
        f"The engine reported a confidence of {field.confidence} for this "
        f"reading, below the {LOW_CONFIDENCE_THRESHOLD} needed to found a "
        f"finding of non-compliance on it, so it has been sent for review "
        f"instead."
    )
