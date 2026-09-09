"""Rule 6(1)(e): how the retail sale price is declared.

One determination is made here and no other: a price the label declares
EXCLUSIVE of all taxes contradicts the clause read with rule 2(m).

These tests exist mostly to pin what the check does **not** do, because that is
where a compliance system is tempted to over-claim:

- the absence of an "inclusive of all taxes" indication is not a violation.
  Whether printing "MRP" alone already indicates it - rule 2(m) defines the
  term as inclusive - is a question of legal construction, not one this system
  settles;
- "in Indian currency" is not checked at all, because `normalise_price` writes
  the currency as a fixed default rather than reading it off the label;
- whether the price is the true maximum is not knowable from a package.
"""

from __future__ import annotations

import pytest

from apps.rules.checks import get_check
from apps.rules.checks.base import (
    CheckContext,
    CheckStatus,
    InvalidCheckParameters,
)
from apps.rules.checks.evidence import LOW_CONFIDENCE_THRESHOLD
from apps.rules.checks.retail_price import check_retail_price_tax_declaration

pytestmark = pytest.mark.django_db


@pytest.fixture
def price_context(completed_run, make_extracted_field):
    """A context whose retail-sale-price reading the test chooses."""

    def _build(raw_value: str, normalized_value=None, *, confidence=0.9):
        make_extracted_field(
            completed_run,
            "retail_sale_price",
            raw_value,
            normalized_value=normalized_value,
            confidence=confidence,
        )
        return CheckContext.from_run(completed_run)

    return _build


# --- registration and parameters --------------------------------------------


def test_the_check_is_registered():
    assert (
        get_check("retail_price_tax_declaration")
        is check_retail_price_tax_declaration
    )


def test_it_takes_no_parameters():
    with pytest.raises(InvalidCheckParameters):
        check_retail_price_tax_declaration(
            {"field_key": "retail_sale_price"},
            CheckContext(run=None, fields_by_key={}),
        )


# --- the one determination --------------------------------------------------


def test_a_price_declared_exclusive_of_taxes_is_a_violation(price_context):
    context = price_context(
        "Price Rs. 100 (excl. of all taxes)",
        {
            "amount": "100",
            "currency": "INR",
            "inclusive_of_all_taxes": False,
            "uncertain": False,
        },
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.status is CheckStatus.FAILED
    assert "EXCLUSIVE of all taxes" in outcome.message
    assert outcome.details["tax_indication_observed"] == "exclusive"


def test_an_exclusive_declaration_on_an_uncertain_reading_is_inconclusive(
    price_context,
):
    """A price with no MRP keyword may not be the retail sale price at all."""
    context = price_context(
        "Rs. 100 excl. of all taxes",
        {
            "amount": "100",
            "inclusive_of_all_taxes": False,
            "uncertain": True,
            "uncertainty_reasons": ["no MRP keyword was found on this line"],
        },
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert outcome.details["tax_indication_observed"] == "exclusive"


def test_an_exclusive_declaration_at_low_confidence_is_inconclusive(price_context):
    context = price_context(
        "MRP Rs. 100 excl. of all taxes",
        {
            "amount": "100",
            "inclusive_of_all_taxes": False,
            "uncertain": False,
        },
        confidence=LOW_CONFIDENCE_THRESHOLD - 0.01,
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE


# --- the passes, and the limits they state ----------------------------------


def test_an_inclusive_declaration_passes(price_context):
    context = price_context(
        "MRP Rs. 120 (incl. of all taxes)",
        {
            "amount": "120",
            "inclusive_of_all_taxes": True,
            "uncertain": False,
        },
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.details["tax_indication_observed"] == "inclusive"


def test_no_tax_wording_at_all_is_a_narrow_pass_not_a_violation(price_context):
    """The load-bearing restraint in this check.

    A label printing "MRP Rs. 120" and nothing else about tax may or may not
    satisfy the clause - rule 2(m) defines the retail sale price as inclusive
    of all taxes, so the answer turns on construction of the words "clearly
    indicate". This system does not settle that, records what it observed, and
    does not manufacture a violation out of it.
    """
    context = price_context(
        "MRP Rs. 120", {"amount": "120", "currency": "INR", "uncertain": False}
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.details["tax_indication_observed"] == "not_observed"
    assert "question of legal construction" in outcome.message


def test_the_currency_is_never_treated_as_evidence(price_context):
    """`currency: INR` is a normaliser default, not a reading of the label.

    Testing rule 6(1)(e)'s "in Indian currency" limb against it would be
    testing our own default and reporting the result as evidence about the
    package.
    """
    context = price_context(
        "MRP Rs. 120", {"amount": "120", "currency": "INR", "uncertain": False}
    )

    outcome = check_retail_price_tax_declaration({}, context)

    assert outcome.details["currency_is_a_normaliser_default_not_a_reading"]
    assert "in Indian currency" in outcome.details["not_checked"]
    assert "in Indian currency" in outcome.message


# --- absences ---------------------------------------------------------------


def test_no_price_defers_to_the_presence_rule(completed_run):
    outcome = check_retail_price_tax_declaration(
        {}, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "presence check" in outcome.message


def test_an_unreadable_photograph_is_inconclusive(empty_run):
    outcome = check_retail_price_tax_declaration(
        {}, CheckContext.from_run(empty_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "clearer, closer photograph" in outcome.message
