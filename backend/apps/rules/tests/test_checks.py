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


# --- a declaration named on the label but not read --------------------------
#
# The second route to INCONCLUSIVE, and the one that used to be a violation.
# A photograph of a curved can catches the panel edge-on: OCR returns the line
# `MRP` and nothing after it. The extraction is usable - other declarations
# were read from the same image - so the "image was unreadable" branch does not
# apply, and before this existed the absent field was reported as FAILED.
#
# "The package declares no MRP" and "the MRP is printed and we could not read
# it" are opposite findings. An absent ExtractedLabelField says both.


def test_a_named_but_unread_declaration_is_inconclusive_not_failed(
    completed_run, make_unread_declaration
):
    """The whole point of this integration, in one assertion."""
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert outcome.status is not CheckStatus.FAILED
    assert outcome.status is not CheckStatus.PASSED


def test_an_unread_declaration_can_never_satisfy_a_presence_check(
    completed_run, make_unread_declaration
):
    """It stops a FAILED. It must never produce a PASSED.

    A PASSED here would record the package as having declared something nobody
    could read - the failure the separate table exists to make impossible,
    checked at the level that would suffer from it.
    """
    make_unread_declaration(
        completed_run, "net_quantity", evidence_text="NET QUANTITY :"
    )
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "net_quantity"}, context)

    assert outcome.status is not CheckStatus.PASSED
    assert context.field("net_quantity") is None, (
        "an unread declaration must not appear among the extracted fields"
    )


def test_the_unread_outcome_says_the_declaration_is_named_not_missing(
    completed_run, make_unread_declaration
):
    """The message is what a user reads. It must not say the declaration is gone.

    Telling someone their package is missing an MRP that is printed on it, in a
    photograph they can see, is worse than telling them nothing.
    """
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert "names this declaration" in outcome.message
    assert "not a finding that the declaration is missing" in outcome.message
    assert "was not found" not in outcome.message


def test_the_evidence_line_survives_into_the_outcome(
    completed_run, make_unread_declaration
):
    """A reviewer has to be shown the line the keyword was read on.

    Without it the finding is unfalsifiable: we saw an MRP keyword, and there
    is nothing to check that against.
    """
    make_unread_declaration(
        completed_run, "retail_sale_price", evidence_text="M.R.P. Rs"
    )
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.evidence_excerpt == "M.R.P. Rs"
    assert outcome.field_key == "retail_sale_price"
    assert outcome.details["declaration_named_but_unread"] is True


def test_the_bounding_box_and_confidence_survive_where_available(
    completed_run, make_unread_declaration
):
    """So the UI can point at the panel that needs re-photographing."""
    make_unread_declaration(
        completed_run,
        "retail_sale_price",
        evidence_text="MRP",
        bounding_box={"x": 513, "y": 1240, "width": 28, "height": 12},
        confidence=0.93,
    )
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.bounding_box == {"x": 513, "y": 1240, "width": 28, "height": 12}
    assert outcome.details["evidence_confidence"] == 0.93


def test_an_unreported_geometry_or_confidence_stays_absent(
    completed_run, make_unread_declaration
):
    """None means the engine did not report it, and must not become a number."""
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.bounding_box is None
    assert outcome.details["evidence_confidence"] is None


def test_an_extracted_field_still_passes_when_another_is_unread(
    completed_run, make_extracted_field, make_unread_declaration
):
    """The new branch is per declaration, not per run.

    An unreadable MRP must not make a net quantity that *was* read stop
    passing. That regression would turn one bad panel into a system-wide
    refusal to say anything.
    """
    make_extracted_field(completed_run, "net_quantity", "500 g")
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    assert (
        check_field_presence({"field_key": "net_quantity"}, context).status
        is CheckStatus.PASSED
    )
    assert (
        check_field_presence({"field_key": "retail_sale_price"}, context).status
        is CheckStatus.INCONCLUSIVE
    )


def test_a_declaration_with_neither_a_field_nor_an_unread_row_still_fails(
    completed_run, make_unread_declaration
):
    """Existing behaviour, asserted beside the new branch so it cannot drift.

    The label was readable, and this declaration was neither read nor named.
    That is still FAILED; narrowing it further would hide real violations.
    """
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "country_of_origin"}, context)

    assert outcome.status is CheckStatus.FAILED
    assert outcome.evidence_excerpt == completed_run.recognised_text


def test_a_field_that_was_read_beats_an_unread_row_for_the_same_key(
    completed_run, make_extracted_field, make_unread_declaration
):
    """Defensive: the ML layer promises these never overlap.

    `RuleBasedFieldExtractor.unread_declarations` skips any key already in
    `fields`. If a future engine breaks that promise, a reading must still win
    - it carries a value, and the unread row by definition does not.
    """
    make_extracted_field(completed_run, "retail_sale_price", "MRP Rs. 349.00")
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(completed_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.evidence_excerpt == "MRP Rs. 349.00"


def test_several_unread_declarations_are_each_reachable(
    completed_run, make_unread_declaration
):
    """A panel cut off by the frame names more than one declaration at once."""
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    make_unread_declaration(
        completed_run, "net_quantity", evidence_text="NET QUANTITY : 1"
    )
    make_unread_declaration(
        completed_run, "best_before", evidence_text="BEST BEFORE 2 YE"
    )
    context = CheckContext.from_run(completed_run)

    assert set(context.unread_by_key) == {
        "retail_sale_price",
        "net_quantity",
        "best_before",
    }
    for key in ("retail_sale_price", "net_quantity", "best_before"):
        outcome = check_field_presence({"field_key": key}, context)
        assert outcome.status is CheckStatus.INCONCLUSIVE, key
        assert outcome.evidence_excerpt, key


def test_an_unreadable_image_still_wins_over_an_unread_row(
    empty_run, make_unread_declaration
):
    """Order of the two INCONCLUSIVE branches, pinned.

    Both reach the same status, so this is about the *message*: telling someone
    no readable text was extracted is more useful when their whole photograph
    failed, and it is the branch that was there first.
    """
    make_unread_declaration(empty_run, "retail_sale_price", evidence_text="MRP")
    context = CheckContext.from_run(empty_run)

    outcome = check_field_presence({"field_key": "retail_sale_price"}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "no readable text was extracted" in outcome.message


# --- the context itself -----------------------------------------------------


def test_a_run_with_no_unread_declarations_behaves_exactly_as_before(completed_run):
    """Backward compatibility for every run recorded before this existed."""
    context = CheckContext.from_run(completed_run)

    assert context.unread_by_key == {}
    assert context.unread("retail_sale_price") is None
    assert (
        check_field_presence({"field_key": "retail_sale_price"}, context).status
        is CheckStatus.FAILED
    )


def test_a_context_built_without_unread_declarations_is_still_valid(completed_run):
    """`CheckContext` is constructed directly in places. It must not break."""
    context = CheckContext(run=completed_run, fields_by_key={})

    assert context.unread_by_key == {}
    assert context.unread("net_quantity") is None


def test_the_context_keeps_readings_and_unread_observations_apart(
    completed_run, make_extracted_field, make_unread_declaration
):
    """Merging them is the one mistake this design exists to prevent."""
    make_extracted_field(completed_run, "net_quantity", "500 g")
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")

    context = CheckContext.from_run(completed_run)

    assert set(context.fields_by_key) == {"net_quantity"}
    assert set(context.unread_by_key) == {"retail_sale_price"}
    assert set(context.fields_by_key).isdisjoint(context.unread_by_key)
    assert context.unread("net_quantity") is None
    assert context.field("retail_sale_price") is None


def test_the_context_loads_unread_declarations_in_one_query(
    completed_run, make_unread_declaration, django_assert_num_queries
):
    """Two queries per check, not two per rule - the guarantee fields have."""
    make_unread_declaration(completed_run, "retail_sale_price", evidence_text="MRP")
    make_unread_declaration(completed_run, "net_quantity", evidence_text="NET QTY")

    with django_assert_num_queries(2):
        context = CheckContext.from_run(completed_run)

    assert len(context.unread_by_key) == 2


def test_an_unread_row_cannot_hold_a_value(completed_run, make_unread_declaration):
    """Asserted against the schema, not against a convention.

    The reason this is a separate table is that a value-less field would pass a
    presence check. If someone adds a `raw_value` column here, that protection
    is gone and this fails.
    """
    unread = make_unread_declaration(completed_run, "retail_sale_price")
    columns = {f.name for f in unread._meta.get_fields()}

    assert "raw_value" not in columns
    assert "normalized_value" not in columns
    assert "value" not in columns
