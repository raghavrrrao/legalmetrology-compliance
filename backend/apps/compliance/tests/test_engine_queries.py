"""Query-count regression tests for the compliance engine.

These exist because the obvious way to write `applies_to_category_codes` -
`self.applies_to_categories.values_list("code", flat=True)` - silently defeats
`prefetch_related`. `values_list` builds a fresh queryset and ignores the
prefetch cache, so evaluating N rules issued N extra queries. It was measured
at 2+N before the fix and 2 after.

Nothing about that is visible in a normal functional test: the results were
correct, just one query per rule. A full Legal Metrology rule set is plausibly
50-100 rules, and every compliance check pays it.

If one of these fails after your change, you have reintroduced an N+1. Do not
raise the bound to make it pass.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.compliance.services import engine

pytestmark = pytest.mark.django_db


def _queries_for_applicable_rules(product) -> int:
    with CaptureQueriesContext(connection) as captured:
        engine.applicable_rules(product)
    return len(captured.captured_queries)


def test_rule_applicability_does_not_scale_with_rule_count(
    product, make_rule, category
):
    """Query count must be flat, not linear in the number of rules."""
    for index in range(3):
        make_rule(f"Q-{index:03d}", categories=[category])
    with_three = _queries_for_applicable_rules(product)

    for index in range(3, 15):
        make_rule(f"Q-{index:03d}", categories=[category])
    with_fifteen = _queries_for_applicable_rules(product)

    assert with_three == with_fifteen, (
        f"applicable_rules issued {with_three} queries for 3 rules and "
        f"{with_fifteen} for 15 - the count grows with the rule set, which "
        f"means a prefetch is being bypassed."
    )


def test_rule_applicability_query_count_is_small(product, make_rule, category):
    """A concrete ceiling, so a regression is caught even at a fixed rule count."""
    for index in range(10):
        make_rule(f"Q-{index:03d}", categories=[category])

    assert _queries_for_applicable_rules(product) <= 3


def test_evaluating_many_rules_does_not_scale_with_violation_count(
    completed_run, make_rule, category, django_assert_max_num_queries
):
    """Recording violations must not re-query the extracted fields per violation.

    Every rule here fails, so this is the worst case: one violation and one
    evidence row each.
    """
    for index in range(8):
        make_rule(f"V-{index:03d}", verified=True, categories=[category])

    # Bound covers: rule lookup, prefetch, field load, the check row, then two
    # inserts per violation. It is deliberately not tight enough to be brittle,
    # but far below the ~3x growth an N+1 here would produce.
    with django_assert_max_num_queries(30):
        check = engine.evaluate(completed_run)

    assert check.violations.count() == 8
