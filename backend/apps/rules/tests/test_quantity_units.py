"""The rule 13 unit validators, and the vocabulary they depend on.

Two clauses, both transcribed verbatim, both purely textual:

    13(5)  the net quantity must be in SI units, or by number
    13(4)  no dozen, score, gross or great gross

The distinction these tests exist to pin is the three-way outcome of the SI
check. An unplaceable unit is INCONCLUSIVE, never a violation, because `oz`
misread from a smudged `g` is indistinguishable here from a genuine ounce -
and turning an OCR defect into a legal finding is the failure mode this whole
repository is built against.
"""

from __future__ import annotations

import pytest

from apps.rules.checks import get_check
from apps.rules.checks.base import (
    CheckContext,
    CheckStatus,
    InvalidCheckParameters,
)
from apps.rules.checks.quantity_units import (
    _COUNT_UNITS,
    _SI_MASS_UNITS,
    _SI_VOLUME_UNITS,
    check_prohibited_counting_unit,
    check_si_unit,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def quantity_context(completed_run, make_extracted_field):
    """A context whose net-quantity reading the test chooses."""

    def _build(raw_value: str, normalized_value=None) -> CheckContext:
        make_extracted_field(
            completed_run,
            "net_quantity",
            raw_value,
            normalized_value=normalized_value,
        )
        return CheckContext.from_run(completed_run)

    return _build


# ---------------------------------------------------------------------------
# The vocabulary must not drift from the extractor's
# ---------------------------------------------------------------------------


def test_the_si_unit_vocabulary_matches_the_extractors():
    """The price of not importing across the ML boundary, paid here.

    `quantity_units` restates the unit sets rather than importing
    `labelextract.fields.normalisation`, because only the extraction service
    may reach the ML runtime. This test imports both - tests are exempt from
    that boundary - and fails the moment either side learns a spelling the
    other has not, which is the drift the restatement would otherwise risk.
    """
    from labelextract.fields.normalisation import (
        _COUNT_UNITS as ml_count,
        _MASS_TO_GRAMS as ml_mass,
        _VOLUME_TO_MILLILITRES as ml_volume,
    )

    assert _SI_MASS_UNITS == frozenset(ml_mass), (
        "the mass units in apps/rules/checks/quantity_units.py no longer match "
        "labelextract's. A unit the extractor emits and this check does not "
        "know is reported INCONCLUSIVE, which silently stops rule 13(5) from "
        "ever passing on it."
    )
    assert _SI_VOLUME_UNITS == frozenset(ml_volume)
    assert _COUNT_UNITS == frozenset(ml_count)


# ---------------------------------------------------------------------------
# Rule 13(5) - SI units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["g", "kg", "mg", "ml", "l", "litre"])
def test_an_si_unit_passes(quantity_context, unit):
    context = quantity_context(f"500 {unit}", {"quantity": 500, "unit": unit})

    outcome = check_si_unit({}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.details["declared_unit"] == unit


@pytest.mark.parametrize("unit", ["n", "pcs", "pieces", "units"])
def test_a_count_unit_passes_under_clause_ii(quantity_context, unit):
    """Rule 13(5)(ii) provides for items sold by number."""
    context = quantity_context(f"10 {unit}", {"quantity": 10, "unit": unit})

    outcome = check_si_unit({}, context)

    assert outcome.status is CheckStatus.PASSED
    assert "sold by number" in outcome.message


@pytest.mark.parametrize(
    "unit,family", [("oz", "ounce"), ("lb", "pound"), ("pint", "pint")]
)
def test_a_known_non_si_unit_fails(quantity_context, unit, family):
    """The only branch that produces a violation, and it is a fact-based one.

    An ounce is not an SI unit; that is not a legal judgement, and rule 13(5)
    is transcribed verbatim.
    """
    context = quantity_context(f"8 {unit}", {"quantity": 8, "unit": unit})

    outcome = check_si_unit({}, context)

    assert outcome.status is CheckStatus.FAILED
    assert outcome.details["unit_family"] == family
    assert "International System of Units" in outcome.message


def test_an_unplaceable_unit_is_inconclusive_not_a_violation(quantity_context):
    """THE load-bearing test of this module.

    A unit we cannot place might be a genuine non-SI declaration or a misread
    character. Reporting it as unlawful would turn every smudged label into a
    legal finding.
    """
    context = quantity_context(
        "500 9m", {"quantity": 500, "unit": "9m", "uncertain": True}
    )

    outcome = check_si_unit({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "not a finding that the declaration is unlawful" in outcome.message
    assert outcome.details["normalisation_uncertain"] is True


def test_a_reading_with_no_normalised_unit_is_inconclusive(quantity_context):
    """A raw string is not a unit.

    Re-deriving one here would put the rules layer in the normaliser's job and
    give two answers that can disagree.
    """
    outcome = check_si_unit({}, quantity_context("500 g"))

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "no unit could be identified" in outcome.message


def test_no_net_quantity_reading_is_inconclusive_not_a_pass(completed_run):
    """Absence of the declaration is rule 6(1)(c)'s finding, not rule 13's.

    Passing here would report compliance with a manner-of-declaration rule on
    a package that may declare no quantity at all.
    """
    outcome = check_si_unit({}, CheckContext.from_run(completed_run))

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "rule 6(1)(c)" in outcome.message


def test_an_unreadable_image_is_inconclusive(empty_run):
    outcome = check_si_unit({}, CheckContext.from_run(empty_run))

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "no readable text" in outcome.message


# ---------------------------------------------------------------------------
# Rule 13(4) - dozen, score, gross, great gross
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["1 dozen", "2 Dozens", "A score of items", "3 gross", "1 great gross"]
)
def test_a_prohibited_counting_unit_fails(quantity_context, raw):
    outcome = check_prohibited_counting_unit({}, quantity_context(raw))

    assert outcome.status is CheckStatus.FAILED
    assert "13(4)" in outcome.message


def test_gross_weight_is_not_a_counting_unit(quantity_context):
    """'Gross Weight' is ordinary and lawful on a package.

    Matching it would report a violation against a correctly labelled product,
    which is worse than the under-claim of not catching every phrasing.
    """
    outcome = check_prohibited_counting_unit(
        {}, quantity_context("Gross Weight 550 g")
    )

    assert outcome.status is CheckStatus.PASSED


def test_a_clean_declaration_passes_and_states_what_was_not_checked(
    quantity_context,
):
    """The clause also bars units 'or the like', which no list can close.

    The pass therefore says so, rather than reading as a clean bill of health
    on the whole clause.
    """
    outcome = check_prohibited_counting_unit({}, quantity_context("500 g"))

    assert outcome.status is CheckStatus.PASSED
    assert "or the like" in outcome.message
    assert outcome.details["scope"] == "net_quantity declaration only"


def test_the_counting_check_ignores_text_outside_the_declaration(
    completed_run, make_extracted_field
):
    """Scoped to the net-quantity reading, not the whole recognised text.

    The run's text mentions a dozen in prose; the declaration does not. Rule
    13(4) does reach the whole package, but scanning every line would flag
    lawful wording, and a false violation is the worse error.
    """
    completed_run.recognised_text = "Baker's dozen promotion inside!"
    completed_run.save()
    make_extracted_field(completed_run, "net_quantity", "500 g")

    outcome = check_prohibited_counting_unit(
        {}, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.PASSED


# ---------------------------------------------------------------------------
# Registration and parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("check_type", ["si_unit", "prohibited_counting_unit"])
def test_both_checks_are_registered(check_type):
    assert get_check(check_type) is not None


@pytest.mark.parametrize("check_type", ["si_unit", "prohibited_counting_unit"])
def test_neither_check_accepts_parameters(check_type, quantity_context):
    """Both are fixed to the net quantity, because rule 13 is about it.

    Pointing one at another declaration would ask a question the clause does
    not ask, so a stray parameter is a configuration error rather than
    something to ignore.
    """
    from apps.rules.checks import validate_parameters

    with pytest.raises(InvalidCheckParameters):
        validate_parameters(check_type, {"field_key": "retail_sale_price"})
