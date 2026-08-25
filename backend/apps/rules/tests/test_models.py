"""Rule model invariants."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.rules.models import ComplianceRule

pytestmark = pytest.mark.django_db


def test_verified_rule_requires_a_source_note(make_rule):
    """Enforced on the model as well as in the loader, so no path bypasses it."""
    rule = make_rule("R-1", verified=True)
    rule.source_note = ""

    with pytest.raises(ValidationError) as exc:
        rule.full_clean(exclude=["applies_to_categories"])

    assert "source_note" in exc.value.message_dict


def test_unverified_rule_needs_no_source_note(make_rule):
    """The contrast case: drafting a rule must not require verifying it first.

    `full_clean` raising here would mean nobody could author a draft rule,
    which is how the team is expected to work before legal review.
    """
    rule = make_rule("R-2", verified=False)

    rule.full_clean(exclude=["applies_to_categories"])  # must not raise

    assert rule.is_verified is False
    assert rule.source_note == ""


def test_reversed_effective_dates_are_rejected(make_rule):
    rule = make_rule("R-3")
    rule.effective_from = date(2020, 1, 1)
    rule.effective_to = date(2019, 1, 1)

    with pytest.raises(ValidationError):
        rule.full_clean(exclude=["applies_to_categories"])


def test_is_verified_reflects_source_status(make_rule):
    assert make_rule("R-4", verified=True).is_verified is True
    assert make_rule("R-5", verified=False).is_verified is False


@pytest.mark.parametrize(
    ("from_date", "to_date", "expected"),
    [
        (None, None, True),
        (date(2000, 1, 1), None, True),
        (date(2099, 1, 1), None, False),
        (None, date(2000, 1, 1), False),
        (date(2000, 1, 1), date(2099, 1, 1), True),
    ],
)
def test_in_force_window(make_rule, from_date, to_date, expected):
    rule = make_rule("R-W", effective_from=from_date, effective_to=to_date)
    assert rule.is_in_force_on(date(2026, 8, 25)) is expected


def test_empty_category_list_means_every_commodity(make_rule):
    rule = make_rule("R-U", categories=[])
    assert rule.applies_to_category_codes(["anything"]) is True


def test_targeted_rule_only_matches_its_categories(make_rule, category):
    rule = make_rule("R-T", categories=[category])

    assert rule.applies_to_category_codes(["packaged-food"]) is True
    assert rule.applies_to_category_codes(["cosmetics"]) is False


def test_rule_code_is_unique(make_rule):
    from django.db import IntegrityError

    make_rule("R-DUP")
    with pytest.raises(IntegrityError):
        make_rule("R-DUP")
