"""The `field_presence` validator and the check registry.

The validator is purely mechanical: it answers "was this declaration found?"
and nothing else. Its three-way outcome is what stops an unreadable photograph
being reported as a legal violation.
"""

import pytest

from apps.rules import checks
from apps.rules.checks.base import CheckContext, CheckStatus
from apps.rules.checks.base import InvalidCheckParameters
from apps.rules.checks.field_presence import (
    check_field_presence,
    validate_field_presence_parameters,
)

pytestmark = pytest.mark.django_db


def test_registry_exposes_the_builtin_check():
    assert "field_presence" in list(checks.available_check_types())
    assert checks.is_registered("field_presence")


def test_unknown_check_type_raises():
    with pytest.raises(checks.UnknownCheckTypeError):
        checks.get_check("does-not-exist")


def test_duplicate_registration_is_rejected():
    """Otherwise behaviour would depend on import order."""
    with pytest.raises(ValueError):
        checks.register_check("field_presence", check_field_presence)


# --- the three outcomes -----------------------------------------------------


def test_present_field_passes(completed_run, make_extracted_field):
    make_extracted_field(completed_run, "net_quantity", "500 g")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "net_quantity"}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.evidence_excerpt == "500 g"


def test_absent_field_fails_when_the_image_was_readable(completed_run):
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "net_quantity"}, context)

    assert outcome.status is CheckStatus.FAILED
    # The evidence for an absence is what we did read.
    assert outcome.evidence_excerpt == completed_run.recognised_text


def test_absent_field_is_inconclusive_when_the_image_was_unreadable(empty_run):
    """The distinction the whole design rests on.

    Same absent field, different extraction quality, different conclusion.
    """
    context = CheckContext.from_run(empty_run)

    outcome = check_field_presence({"field_key": "net_quantity"}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert outcome.status is not CheckStatus.FAILED
    assert "not a finding about the package" in outcome.message


def test_inconclusive_message_tells_the_user_what_to_do(empty_run):
    context = CheckContext.from_run(empty_run)
    outcome = check_field_presence({"field_key": "net_quantity"}, context)

    assert "clearer" in outcome.message.lower()


# --- configuration errors ---------------------------------------------------


@pytest.mark.parametrize("parameters", [{}, {"field_key": ""}, {"field_key": 42}])
def test_missing_field_key_raises_rather_than_passing(completed_run, parameters):
    """A misconfigured rule must be loud, never a silent pass."""
    context = CheckContext.from_run(completed_run)
    with pytest.raises(InvalidCheckParameters):
        check_field_presence(parameters, context)


# --- context ----------------------------------------------------------------


def test_context_loads_fields_once(completed_run, make_extracted_field):
    make_extracted_field(completed_run, "net_quantity", "500 g")
    make_extracted_field(completed_run, "retail_sale_price", "Rs. 250")

    context = CheckContext.from_run(completed_run)

    assert set(context.fields_by_key) == {"net_quantity", "retail_sale_price"}
    assert context.extraction_was_usable is True


def test_empty_run_is_not_usable(empty_run):
    assert CheckContext.from_run(empty_run).extraction_was_usable is False


# --- the registry carries a parameter validator, not just a validator -------


def test_every_registered_check_declares_a_parameter_validator():
    """The gap this closes: parameter validation used to be hardcoded in the
    loader behind `if check_type != "field_presence"`, so any check type added
    later silently received none.
    """
    for check_type in checks.available_check_types():
        spec = checks.get_spec(check_type)
        assert callable(spec.parameter_validator), check_type
        assert spec.description, f"{check_type} has no description"


def test_validate_parameters_rejects_a_bad_field_key():
    with pytest.raises(InvalidCheckParameters):
        checks.validate_parameters("field_presence", {"field_key": "net_qty"})


def test_validate_parameters_accepts_a_good_field_key():
    parameters = {"field_key": "net_quantity"}

    checks.validate_parameters("field_presence", parameters)  # must not raise

    # The validator inspects, never rewrites - a rule file must round-trip.
    assert parameters == {"field_key": "net_quantity"}


def test_validate_parameters_on_an_unknown_check_type_raises():
    with pytest.raises(checks.UnknownCheckTypeError):
        checks.validate_parameters("value_check", {})


def test_planned_check_types_are_documented_but_not_registered():
    """They must not be usable - a rule naming one is rejected, not silently run."""
    assert checks.PLANNED_CHECK_TYPES
    for check_type in checks.PLANNED_CHECK_TYPES:
        assert not checks.is_registered(check_type)


@pytest.mark.parametrize("bad", [{}, {"field_key": ""}, {"field_key": 42}])
def test_field_presence_parameter_validator_rejects_missing_key(bad):
    with pytest.raises(InvalidCheckParameters):
        validate_field_presence_parameters(bad)


def test_context_exposes_the_source_image_for_visual_checks(completed_run):
    """A future visual_check needs a defined route to the image and its size."""
    context = CheckContext.from_run(completed_run)

    assert context.image.pk == completed_run.image_id
    assert context.image.width > 0
    assert context.image.height > 0
