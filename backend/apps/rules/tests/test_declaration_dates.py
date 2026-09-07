"""Rule 6(1)(d): does the date declaration establish a month and a year?

Two things are pinned here, and the second is the reason the check exists.

**No printed format is enforced.** The clause prescribes none, so `12/2024`,
`DEC 2024` and anything else `labelextract` can resolve all pass, and a reading
it cannot resolve is sent for review rather than reported as a violation. A
check that rejected an unusual printing would be enforcing a requirement the
source does not contain.

**An ambiguous date does not pass.** `03/04/2025` reads as 3 April or as 4
March; the year is settled either way and the month is not, so the clause's
requirement is not established. Passing it would claim a month this system
never determined.
"""

from __future__ import annotations

import pytest

from apps.rules.checks import get_check, validate_parameters
from apps.rules.checks.base import (
    CheckContext,
    CheckStatus,
    InvalidCheckParameters,
)
from apps.rules.checks.declaration_dates import check_month_year_declaration

pytestmark = pytest.mark.django_db

_PARAMS = {"field_key": "date_of_manufacture"}


@pytest.fixture
def date_context(completed_run, make_extracted_field):
    """A context whose manufacture-date reading the test chooses."""

    def _build(raw_value: str, normalized_value=None, *, confidence=0.9):
        make_extracted_field(
            completed_run,
            "date_of_manufacture",
            raw_value,
            normalized_value=normalized_value,
            confidence=confidence,
        )
        return CheckContext.from_run(completed_run)

    return _build


# --- registration and parameters --------------------------------------------


def test_the_check_is_registered():
    assert get_check("month_year_declaration") is check_month_year_declaration


def test_a_field_key_is_required():
    with pytest.raises(InvalidCheckParameters):
        validate_parameters("month_year_declaration", {})


def test_only_a_date_declaration_may_be_named():
    """Asking a net quantity whether it states a month and a year is nonsense.

    Caught at load time, because a rule naming the wrong key would otherwise
    look like a check that simply never matches - which is indistinguishable
    from a compliant product.
    """
    with pytest.raises(InvalidCheckParameters) as raised:
        validate_parameters("month_year_declaration", {"field_key": "net_quantity"})

    assert "date declaration" in str(raised.value)


@pytest.mark.parametrize(
    "field_key",
    ["date_of_manufacture", "date_of_packing", "date_of_import", "best_before"],
)
def test_every_date_declaration_is_accepted(field_key):
    validate_parameters("month_year_declaration", {"field_key": field_key})


# --- the pass, over every printing the normaliser can resolve ---------------


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("MFG 12/2024", {"year_month": "2024-12", "uncertain": False}),
        ("Mfd: DEC 2024", {"year_month": "2024-12", "uncertain": False}),
        ("Packed on 25 Dec 2024", {"date": "2024-12-25", "uncertain": False}),
    ],
)
def test_a_resolved_month_and_year_passes_whatever_the_printing(
    date_context, raw, normalised
):
    """The Rules prescribe no format, so none is enforced."""
    outcome = check_month_year_declaration(_PARAMS, date_context(raw, normalised))

    assert outcome.status is CheckStatus.PASSED
    assert "no format" in outcome.message


def test_the_pass_does_not_claim_the_date_is_true(date_context):
    context = date_context("MFG 12/2024", {"year_month": "2024-12", "uncertain": False})

    outcome = check_month_year_declaration(_PARAMS, context)

    assert "cannot be established from a photograph" in outcome.message


# --- everything that must NOT become a violation ----------------------------


def test_an_ambiguous_date_is_inconclusive_not_a_violation(date_context):
    """DD/MM and MM/DD are both in use and the label does not say which.

    The month is the part the clause needs and the part that is unsettled.
    """
    context = date_context(
        "MFG 03/04/2025",
        {
            "uncertain": True,
            "uncertainty_reasons": [
                "both DD/MM and MM/DD are valid readings of this date"
            ],
            "candidates": ["2025-04-03", "2025-03-04"],
        },
    )

    outcome = check_month_year_declaration(_PARAMS, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "2025-04-03" in outcome.message
    assert "2025-03-04" in outcome.message


def test_a_date_read_from_the_next_line_is_inconclusive(date_context):
    """A month and a year are legible; that they are the MFG date is not.

    The extractor marks a value read from the line after its keyword uncertain,
    because nothing but adjacency ties the two together.
    """
    context = date_context(
        "MFG",
        {
            "year_month": "2024-12",
            "uncertain": True,
            "uncertainty_reasons": [
                "the date was read from the line after the keyword"
            ],
        },
    )

    outcome = check_month_year_declaration(_PARAMS, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE


def test_a_shelf_life_duration_is_inconclusive_without_a_false_confidence_claim(
    date_context,
):
    """"Best before 9 months from packaging" carries no month and no year.

    The reading is sound and high-confidence; it simply does not answer the
    question. The message must not blame the confidence, which would be false.
    """
    context = date_context(
        "Best before 9 months from packaging",
        {"duration_value": 9, "duration_unit": "months", "uncertain": False},
        confidence=0.98,
    )

    outcome = check_month_year_declaration(
        {"field_key": "best_before"}, context
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "confidence" not in outcome.message


def test_no_date_declaration_defers_to_the_presence_rule(completed_run):
    outcome = check_month_year_declaration(
        _PARAMS, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "presence check" in outcome.message


def test_an_unreadable_photograph_is_inconclusive(empty_run):
    outcome = check_month_year_declaration(
        _PARAMS, CheckContext.from_run(empty_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "clearer, closer photograph" in outcome.message


@pytest.mark.parametrize(
    "normalised",
    [
        None,
        {"uncertain": True},
        {"uncertain": True, "candidates": ["2025-04-03", "2025-03-04"]},
        {"year_month": "2024-12", "uncertain": False},
        {"duration_value": 9, "duration_unit": "months", "uncertain": False},
    ],
)
def test_nothing_here_can_ever_produce_a_violation(date_context, normalised):
    """The whole check is pass-or-review, by construction.

    A malformed date is not evidence of an unlawful declaration - the Rules
    prescribe no form for it - so there is no branch that returns FAILED, and
    this test exists so that adding one has to be a deliberate decision.
    """
    context = date_context("MFG 12/2024", normalised)

    outcome = check_month_year_declaration(_PARAMS, context)

    assert outcome.status is not CheckStatus.FAILED
