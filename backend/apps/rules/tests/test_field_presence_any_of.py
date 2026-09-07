"""The `field_presence_any_of` validator, and the false violation it removes.

Rule 6(1)(a) is disjunctive: a package satisfies it by declaring the
manufacturer, or the manufacturer and the packer, or - for an imported package
- the importer. `rules/INVENTORY.md` records that LM-PC-0001 shipped INACTIVE
because `field_presence` tests exactly one key, so a rule keyed on
`manufacturer_name` would report a lawfully labelled imported package as
NON_COMPLIANT.

The first test below is that exact package, and it is why this check exists.
"""

from __future__ import annotations

import pytest

from apps.rules.checks import validate_parameters
from apps.rules.checks.base import (
    CheckContext,
    CheckStatus,
    InvalidCheckParameters,
)
from apps.rules.checks.field_presence_any_of import check_field_presence_any_of

pytestmark = pytest.mark.django_db

#: The disjunction rule 6(1)(a) states, as LM-PC-0001 configures it.
CLAUSE_6_1_A = {
    "field_keys": ["manufacturer_name", "packer_name", "importer_name"]
}


def test_an_imported_package_declaring_only_the_importer_passes(
    completed_run, make_extracted_field
):
    """The false violation this check was written to remove.

    A lawfully labelled imported package declares the importer and no
    manufacturer. Under `field_presence` on `manufacturer_name` it failed.
    """
    make_extracted_field(completed_run, "importer_name", "Acme Imports Pvt Ltd")

    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.PASSED
    assert outcome.field_key == "importer_name"
    assert outcome.evidence_excerpt == "Acme Imports Pvt Ltd"
    assert outcome.details["satisfied_by"] == ["importer_name"]


def test_a_domestic_package_declaring_only_the_manufacturer_passes(
    completed_run, make_extracted_field
):
    make_extracted_field(completed_run, "manufacturer_name", "Bharat Foods Ltd")

    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.PASSED
    assert outcome.field_key == "manufacturer_name"


def test_several_alternatives_present_are_all_reported(
    completed_run, make_extracted_field
):
    """Which alternative satisfied a disjunctive clause is what a reviewer
    checking it against the source needs to see."""
    make_extracted_field(completed_run, "manufacturer_name", "Bharat Foods Ltd")
    make_extracted_field(completed_run, "packer_name", "Bharat Packers")

    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.PASSED
    assert outcome.details["satisfied_by"] == ["manufacturer_name", "packer_name"]


def test_none_of_the_alternatives_present_fails(completed_run):
    """The run read text and found none of the three declarations."""
    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.FAILED
    assert "None of" in outcome.message
    # The message names what WOULD have satisfied it, which a bare "missing
    # manufacturer_name" could not.
    for key in CLAUSE_6_1_A["field_keys"]:
        assert key in outcome.message


def test_an_unreadable_image_is_inconclusive_not_a_failure(empty_run):
    """A blurred photograph is never a missing declaration."""
    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(empty_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "not a finding about the package" in outcome.message


def test_the_failure_carries_what_was_read_as_evidence(
    completed_run,
):
    """For an absence, what we DID read justifies concluding it was absent."""
    outcome = check_field_presence_any_of(
        CLAUSE_6_1_A, CheckContext.from_run(completed_run)
    )

    assert outcome.evidence_excerpt == completed_run.recognised_text


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


def test_a_single_key_is_rejected():
    """One key is not a disjunction.

    Expressing it this way would hide a plain `field_presence` rule behind a
    failure message talking about alternatives that do not exist.
    """
    with pytest.raises(InvalidCheckParameters) as exc:
        validate_parameters("field_presence_any_of", {"field_keys": ["net_quantity"]})

    assert "at least two" in str(exc.value)


def test_an_unknown_field_key_is_rejected():
    """A typo would produce a rule that silently never matches - which looks
    exactly like a compliant product."""
    with pytest.raises(InvalidCheckParameters):
        validate_parameters(
            "field_presence_any_of",
            {"field_keys": ["manufacturer_name", "manufacterer_name"]},
        )


def test_a_duplicated_alternative_is_rejected():
    with pytest.raises(InvalidCheckParameters) as exc:
        validate_parameters(
            "field_presence_any_of",
            {"field_keys": ["manufacturer_name", "manufacturer_name"]},
        )

    assert "duplicate" in str(exc.value)


def test_missing_field_keys_is_rejected():
    with pytest.raises(InvalidCheckParameters):
        validate_parameters("field_presence_any_of", {})


def test_the_shipped_clause_parameters_validate():
    """LM-PC-0001's real configuration, checked against the registry."""
    validate_parameters("field_presence_any_of", CLAUSE_6_1_A)
