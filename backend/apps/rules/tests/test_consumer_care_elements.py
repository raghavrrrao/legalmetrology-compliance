"""Rule 6(2): the elements of the consumer-care declaration.

The clause names four - name, address, telephone number, e-mail address. This
validator tests two of them and says so in every outcome, which is what these
tests pin: a pass here must never read as a pass on the clause.

The other thing pinned is the direction of every doubt. A declaration nobody
could read anything out of, an uncertain interpretation, and a low reported OCR
confidence all produce INCONCLUSIVE, never a violation.
"""

from __future__ import annotations

import pytest

from apps.rules.checks import get_check
from apps.rules.checks.base import (
    CheckContext,
    CheckStatus,
    InvalidCheckParameters,
)
from apps.rules.checks.consumer_care import check_consumer_care_elements
from apps.rules.checks.evidence import LOW_CONFIDENCE_THRESHOLD

pytestmark = pytest.mark.django_db

_RAW = "Consumer care: care@example.com, 1800 123 4567"


@pytest.fixture
def care_context(completed_run, make_extracted_field):
    """A context whose consumer-care reading the test chooses."""

    def _build(normalized_value=None, *, confidence=0.9, raw_value=_RAW):
        make_extracted_field(
            completed_run,
            "consumer_care_contact",
            raw_value,
            normalized_value=normalized_value,
            confidence=confidence,
        )
        return CheckContext.from_run(completed_run)

    return _build


def _certain(**values) -> dict:
    return {**values, "uncertain": False}


# --- registration and parameters --------------------------------------------


def test_the_check_is_registered():
    assert get_check("consumer_care_elements") is check_consumer_care_elements


def test_it_takes_no_parameters():
    """Fixed to the consumer-care declaration, because rule 6(2) is."""
    with pytest.raises(InvalidCheckParameters):
        check_consumer_care_elements(
            {"field_key": "consumer_care_contact"},
            CheckContext(run=None, fields_by_key={}),
        )


# --- the pass, and what it does not claim -----------------------------------


def test_a_telephone_number_and_an_email_pass(care_context):
    context = care_context(
        _certain(emails=["care@example.com"], phones=["1800 123 4567"])
    )

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.PASSED
    assert outcome.details["elements_found"] == {
        "phones": ["1800 123 4567"],
        "emails": ["care@example.com"],
    }


def test_the_pass_says_what_it_did_not_check(care_context):
    """A finding is read on its own, so it has to carry its own limits.

    Rule 6(2) requires a name and an address too. Neither is checked, and a
    pass that did not say so would be read as a pass on the whole clause.
    """
    context = care_context(
        _certain(emails=["care@example.com"], phones=["1800 123 4567"])
    )

    outcome = check_consumer_care_elements({}, context)

    assert "name and the address" in outcome.message
    assert "not a finding that the package complies with rule 6(2)" in (
        outcome.message
    )
    assert outcome.details["elements_not_checked"] == [
        "name of the person or office to be contacted",
        "address of the person or office to be contacted",
    ]


# --- the violations ---------------------------------------------------------


def test_a_missing_email_is_a_violation_naming_the_element(care_context):
    """The finding has to say WHICH element, not that something is wrong."""
    context = care_context(_certain(phones=["1800 123 4567"]))

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.FAILED
    assert "e-mail address" in outcome.message
    assert outcome.details["elements_not_found"] == ["e-mail address"]
    assert outcome.evidence_excerpt == _RAW


def test_a_missing_telephone_number_is_a_violation_naming_the_element(
    care_context,
):
    context = care_context(_certain(emails=["care@example.com"]))

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.FAILED
    assert outcome.details["elements_not_found"] == ["telephone number"]


# --- everything that must NOT become a violation ----------------------------


def test_an_unreadable_photograph_is_inconclusive(empty_run):
    outcome = check_consumer_care_elements({}, CheckContext.from_run(empty_run))

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "clearer, closer photograph" in outcome.message


def test_no_declaration_at_all_defers_to_the_presence_rule(completed_run):
    """Absence is rule 6(2)'s presence check, not this one's.

    Reporting it here as well would produce two violations for one defect and
    would make a package declaring nothing look worse than one declaring half
    of what it owes.
    """
    outcome = check_consumer_care_elements(
        {}, CheckContext.from_run(completed_run)
    )

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "presence check" in outcome.message


def test_a_keyword_with_no_readable_contact_is_inconclusive(care_context):
    """"Customer care:" and nothing legible after it is a photograph problem."""
    context = care_context(
        {"uncertain": True, "uncertainty_reasons": ["nothing was read"]}
    )

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "neither a telephone number nor an e-mail address" in outcome.message


def test_a_missing_element_on_an_uncertain_reading_is_inconclusive(care_context):
    """A phone number with no consumer-care keyword may not be one at all.

    The extractor says so by marking the reading uncertain. Failing the package
    for a missing e-mail on the strength of a reading the extractor would not
    commit to would found a legal finding on a guess.
    """
    context = care_context(
        {
            "phones": ["9876543210"],
            "uncertain": True,
            "uncertainty_reasons": [
                "a phone number was read with no consumer-care keyword"
            ],
        }
    )

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert outcome.details["normalisation_uncertain"] is True


def test_a_missing_element_on_a_low_confidence_reading_is_inconclusive(
    care_context,
):
    context = care_context(
        _certain(phones=["1800 123 4567"]),
        confidence=LOW_CONFIDENCE_THRESHOLD - 0.01,
    )

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
    assert "below the" in outcome.message


def test_a_missing_element_with_no_reported_confidence_still_fails(care_context):
    """NULL confidence is unknown, not low.

    Treating it as low would disable this check entirely for any engine that
    reports no confidence. The finding records which it was.
    """
    context = care_context(_certain(phones=["1800 123 4567"]), confidence=None)

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.FAILED
    assert outcome.details["confidence_reported"] is False


def test_a_reading_with_no_normalised_value_is_inconclusive(care_context):
    """No normaliser ran, so nothing has vouched for any element."""
    context = care_context(None)

    outcome = check_consumer_care_elements({}, context)

    assert outcome.status is CheckStatus.INCONCLUSIVE
