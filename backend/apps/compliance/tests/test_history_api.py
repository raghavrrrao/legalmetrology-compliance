"""`GET /api/v1/compliance/` - the results already stored, newest first.

This is the read side of the compliance API: not "what do the rules make of
this reading?" but "what has been checked, when, and what came out?". It is
what an inspection-history screen lists and navigates from.

What is asserted here is the endpoint's contract and the two properties a
history list is worth nothing without:

- **the order is total.** Newest first, and equal timestamps broken by a fixed
  key. An unstable sort under pagination does not merely look untidy - it shows
  one result twice and hides another, and a reviewer has no way to notice.
- **the rows are light.** A history row carries the verdict and the counts, not
  the trace. `findings`, `violations`, evidence excerpts, bounding boxes and
  the reading stay on `GET /api/v1/compliance/<uuid>/`, and this suite fails if
  any of them leaks into a list row.

Checks are built directly rather than through the engine wherever the test is
about the list rather than about a verdict: the engine has its own suites, and
a history test that had to produce real violations to assert an ordering would
be measuring the wrong thing. The tests about counts go through the API's own
POST, so the numbers are counted from rows the engine actually wrote.
"""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from labelextract.contracts import LabelFieldKey

from apps.compliance.models import ComplianceCheck

pytestmark = pytest.mark.django_db

#: The complete list-row contract. Asserted as an exact set, in both
#: directions: a field added without a documented decision fails here, and so
#: does a field silently dropped from under a client.
LIST_FIELDS = {
    "id",
    "status",
    "result",
    "result_display",
    "created_at",
    "completed_at",
    "engine_version",
    "extraction_run_id",
    "product_category_code",
    "findings_count",
    "violations_count",
}

#: Detail-only keys. Present on `GET /api/v1/compliance/<uuid>/`, and a history
#: row that carried any of them would be shipping the whole trace per row.
DETAIL_ONLY_FIELDS = [
    "summary",
    "findings",
    "violations",
    "extraction",
    "image",
    "rules_evaluated",
    "rules_passed",
    "rules_failed",
    "rules_inconclusive",
    "processing_ms",
]


@pytest.fixture(autouse=True)
def _demo_api_open(settings):
    """Run these tests with the demo switch on.

    Its off position is asserted explicitly in the permissions section below.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True


@pytest.fixture
def make_check(db, completed_run):
    """A stored `ComplianceCheck`, without running the engine to get one."""

    def _make(**kwargs) -> ComplianceCheck:
        return ComplianceCheck.objects.create(
            extraction_run=kwargs.pop("extraction_run", completed_run),
            product=kwargs.pop("product", completed_run.image.product),
            status=kwargs.pop("status", ComplianceCheck.Status.COMPLETED),
            result=kwargs.pop("result", ComplianceCheck.Result.REVIEW_REQUIRED),
            engine_version=kwargs.pop("engine_version", "test-1.0"),
            **kwargs,
        )

    return _make


def _stamp(check: ComplianceCheck, seconds_ago: int) -> ComplianceCheck:
    """Force a check's `created_at`, so an ordering test is not clock-dependent.

    `created_at` is `auto_now_add`, and on a coarse clock several rows created
    in a loop genuinely share a timestamp - which is worth knowing, because it
    means equal timestamps are ordinary rather than exotic, and it is why the
    ordering carries a tie-breaker at all. A test about "newest first" needs
    distinct timestamps to be testing that rather than the clock, so it says
    which is newer instead of hoping.

    Written with `update` because `auto_now_add` ignores an assigned value.
    """
    when = timezone.now() - timedelta(seconds=seconds_ago)
    ComplianceCheck.objects.filter(pk=check.pk).update(created_at=when)
    check.refresh_from_db()
    return check


def _history(client, **params):
    return client.get(reverse("v1:compliance-evaluate"), params)


def _evaluate(client, run, **extra):
    return client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": str(run.pk), **extra},
        content_type="application/json",
    )


# --- the response envelope ----------------------------------------------------


def test_an_empty_history_is_an_empty_page_not_a_404(client):
    """Nothing evaluated yet is a state a history screen must be able to draw."""
    response = _history(client)

    assert response.status_code == 200
    assert response.json() == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


def test_one_stored_result_is_returned_with_the_documented_envelope(
    client, make_check
):
    check = make_check(result=ComplianceCheck.Result.NON_COMPLIANT)

    body = _history(client).json()

    assert body["count"] == 1
    assert body["next"] is None
    assert body["previous"] is None
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == str(check.pk)


def test_the_envelope_keys_are_stable(client, make_check):
    make_check()

    assert set(_history(client).json()) == {"count", "next", "previous", "results"}


def test_several_results_are_all_counted(client, make_check):
    for _ in range(5):
        make_check()

    body = _history(client).json()

    assert body["count"] == 5
    assert len(body["results"]) == 5


# --- the row contract ---------------------------------------------------------


def test_a_row_carries_exactly_the_documented_fields(client, make_check, category):
    check = make_check(result=ComplianceCheck.Result.COMPLIANT)

    row = _history(client).json()["results"][0]

    assert set(row) == LIST_FIELDS
    assert row["id"] == str(check.pk)
    assert row["status"] == ComplianceCheck.Status.COMPLETED
    assert row["result"] == ComplianceCheck.Result.COMPLIANT
    # The human label comes from the model's own choices, so the two cannot
    # drift apart.
    assert row["result_display"] == check.get_result_display()
    assert row["engine_version"] == "test-1.0"
    assert row["extraction_run_id"] == str(check.extraction_run_id)
    assert row["product_category_code"] == category.code
    assert row["created_at"]


def test_a_row_carries_none_of_the_detail_only_fields(
    client, completed_run, make_rule
):
    """The whole point of a separate list serializer.

    Built through the API so the check genuinely has findings, violations and
    evidence to leak.
    """
    make_rule("HIST-LEAK", field_key=LabelFieldKey.NET_QUANTITY.value)
    _evaluate(client, completed_run)

    row = _history(client).json()["results"][0]

    for field in DETAIL_ONLY_FIELDS:
        assert field not in row, f"{field} is detail-only and must not be listed"


def test_an_unknown_commodity_category_is_null_not_omitted(client, make_check):
    """Null is load-bearing - see the detail serializer for why."""
    check = make_check()
    check.product.category = None
    check.product.save()

    row = _history(client).json()["results"][0]

    assert row["product_category_code"] is None


def test_a_check_with_no_product_still_lists(client, make_check, completed_run):
    """`product` is nullable, and a history row must not 500 on that."""
    make_check(product=None)

    row = _history(client).json()["results"][0]

    assert row["product_category_code"] is None
    assert row["extraction_run_id"] == str(completed_run.pk)


# --- ordering -----------------------------------------------------------------


def test_the_newest_result_is_first(client, make_check):
    older = _stamp(make_check(engine_version="older"), seconds_ago=60)
    newer = _stamp(make_check(engine_version="newer"), seconds_ago=1)

    rows = _history(client).json()["results"]

    assert [row["id"] for row in rows] == [str(newer.pk), str(older.pk)]


def test_the_order_is_total_when_timestamps_are_equal(client, make_check):
    """`created_at` is not unique, and equal keys must not sort arbitrarily.

    Without the `-id` tie-break the database may return equal-timestamp rows in
    any order it likes, and under pagination that means one result appearing on
    two pages while another is never shown at all.
    """
    checks = [make_check() for _ in range(6)]
    ComplianceCheck.objects.update(created_at=checks[0].created_at)

    first = [row["id"] for row in _history(client).json()["results"]]
    second = [row["id"] for row in _history(client).json()["results"]]

    assert first == second
    assert first == sorted((str(check.pk) for check in checks), reverse=True)


def test_pages_do_not_repeat_or_lose_a_row_on_equal_timestamps(client, make_check):
    """The consequence the tie-break exists to prevent, asserted end to end."""
    checks = [make_check() for _ in range(6)]
    ComplianceCheck.objects.update(created_at=checks[0].created_at)

    page_one = _history(client, page_size=3).json()["results"]
    page_two = _history(client, page_size=3, page=2).json()["results"]

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(seen)) == 6
    assert set(seen) == {str(check.pk) for check in checks}


# --- pagination ----------------------------------------------------------------


def test_the_page_size_can_be_chosen_and_the_count_is_the_total(client, make_check):
    for _ in range(7):
        make_check()

    body = _history(client, page_size=3).json()

    # `count` is how many results exist, not how many this page holds.
    assert body["count"] == 7
    assert len(body["results"]) == 3


def test_next_and_previous_walk_the_pages(client, make_check):
    for _ in range(7):
        make_check()

    first = _history(client, page_size=3).json()
    middle = _history(client, page_size=3, page=2).json()
    last = _history(client, page_size=3, page=3).json()

    assert first["previous"] is None
    assert first["next"] is not None
    assert middle["previous"] is not None
    assert middle["next"] is not None
    assert last["next"] is None
    assert len(last["results"]) == 1


def test_the_pages_together_are_the_whole_history_in_order(client, make_check):
    made = [_stamp(make_check(), seconds_ago=60 - index) for index in range(5)]
    newest_first = [str(check.pk) for check in reversed(made)]

    listed = []
    for page in (1, 2, 3):
        body = _history(client, page_size=2, page=page).json()
        listed += [row["id"] for row in body["results"]]

    assert listed == newest_first


def test_the_default_page_size_is_twenty(client, make_check):
    for _ in range(21):
        make_check()

    body = _history(client).json()

    assert body["count"] == 21
    assert len(body["results"]) == 20


def test_the_page_size_is_capped(client, make_check):
    """An uncapped page size is a lever, not a convenience."""
    for _ in range(5):
        make_check()

    body = _history(client, page_size=100000).json()

    assert len(body["results"]) == 5
    assert body["count"] == 5


def test_a_page_past_the_end_is_a_404_in_the_standard_envelope(client, make_check):
    make_check()

    response = _history(client, page=99)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_non_numeric_page_is_a_404_in_the_standard_envelope(client, make_check):
    make_check()

    response = _history(client, page="not-a-number")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_malformed_page_size_falls_back_to_the_default(client, make_check):
    """DRF's behaviour, left alone: a mistyped page size still returns results."""
    for _ in range(3):
        make_check()

    for bad in ("abc", "-1", "0"):
        response = _history(client, page_size=bad)
        assert response.status_code == 200, bad
        assert len(response.json()["results"]) == 3, bad


# --- the counts ----------------------------------------------------------------


def test_the_counts_report_the_rows_the_detail_endpoint_would_return(
    client, completed_run, make_rule
):
    """Two rules examined, both failed - so two findings and two violations."""
    make_rule("HIST-ONE", field_key=LabelFieldKey.NET_QUANTITY.value)
    make_rule("HIST-TWO", field_key=LabelFieldKey.MANUFACTURER_NAME.value)
    detail = _evaluate(client, completed_run).json()

    row = _history(client).json()["results"][0]

    assert row["findings_count"] == len(detail["findings"]) == 2
    assert row["violations_count"] == len(detail["violations"]) == 2


def test_a_passing_rule_is_a_finding_but_not_a_violation(
    client, completed_run, make_rule, make_extracted_field
):
    """The two counts answer different questions and must not track each other."""
    make_extracted_field(completed_run, LabelFieldKey.NET_QUANTITY.value)
    make_rule("HIST-PASS", field_key=LabelFieldKey.NET_QUANTITY.value)
    _evaluate(client, completed_run)

    row = _history(client).json()["results"][0]

    assert row["findings_count"] == 1
    assert row["violations_count"] == 0


def test_a_check_with_nothing_recorded_counts_zero_not_null(client, make_check):
    """Zero is the honest answer for a check that examined nothing."""
    make_check()

    row = _history(client).json()["results"][0]

    assert row["findings_count"] == 0
    assert row["violations_count"] == 0


def test_the_counts_are_per_check_and_do_not_bleed_between_rows(
    client, completed_run, make_rule, make_check
):
    make_rule("HIST-BLEED", field_key=LabelFieldKey.NET_QUANTITY.value)
    _evaluate(client, completed_run)
    empty = make_check()

    by_id = {row["id"]: row for row in _history(client).json()["results"]}

    assert by_id[str(empty.pk)]["findings_count"] == 0
    evaluated = next(row for row in by_id.values() if row["id"] != str(empty.pk))
    assert evaluated["findings_count"] == 1


# --- query cost -----------------------------------------------------------------


def _queries_for_history(client, **params) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(reverse("v1:compliance-evaluate"), params)
        assert response.status_code == 200
    return len(captured.captured_queries)


def test_listing_does_not_issue_a_query_per_row(client, make_check):
    """The count must be flat in the number of results, not linear.

    A history page that costs a query per row - for the category, or for the
    findings and violations counts - is the regression this endpoint is most
    likely to acquire. If this fails after your change, you have reintroduced
    an N+1. Do not raise the bound to make it pass.
    """
    for _ in range(2):
        make_check()
    with_two = _queries_for_history(client)

    for _ in range(18):
        make_check()
    with_twenty = _queries_for_history(client)

    assert with_two == with_twenty, (
        f"history issued {with_two} queries for 2 results and {with_twenty} "
        f"for 20 - the cost grows with the page, which means a per-row query "
        f"has crept in."
    )


def test_the_history_query_count_is_small(client, make_check):
    """A concrete ceiling, so a regression is caught even at a fixed row count."""
    for _ in range(10):
        make_check()

    # The count query and the page query. Anything much above this is a join or
    # a lookup that should have been part of one of the two.
    assert _queries_for_history(client) <= 4


# --- permissions ----------------------------------------------------------------


def test_the_history_denies_anonymous_callers_by_default(client, make_check, settings):
    """Adding an endpoint must not add an unguarded one."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    make_check()

    response = _history(client)

    assert response.status_code in (401, 403)
    assert response.json()["error"]["code"] in (
        "not_authenticated",
        "permission_denied",
    )


def test_an_authenticated_user_is_allowed_with_the_switch_off(
    client, make_check, settings, user
):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    client.force_login(user)
    make_check()

    response = _history(client)

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_the_demo_switch_opens_the_history_to_anonymous_callers(
    client, make_check, settings
):
    """The documented relaxation, asserted in its on position too."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    make_check()

    assert _history(client).status_code == 200


def test_the_history_is_not_scoped_to_the_requesting_user(
    client, make_check, user, settings
):
    """The known limitation, asserted rather than left implicit.

    `ComplianceCheck` has no ownership model - a check requested anonymously
    has no owner at all - so every caller who is allowed through sees every
    stored check. This is the same limitation `GET /api/v1/compliance/<uuid>/`
    already has, made more visible by listing what previously had to be
    guessed. It is documented in `docs/api.md` and belongs to the
    authentication work, not to this view. If ownership scoping is ever added,
    this test is the one to change - deliberately, not by accident.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    somebody_elses = make_check()
    client.force_login(user)

    body = _history(client).json()

    assert [row["id"] for row in body["results"]] == [str(somebody_elses.pk)]
    assert ComplianceCheck.objects.get().requested_by_id is None


# --- the endpoints this one must not have broken ---------------------------------


def test_evaluating_on_the_same_url_still_returns_201(
    client, completed_run, make_rule
):
    """The collection now answers two methods; POST is unchanged."""
    make_rule("HIST-POST", field_key=LabelFieldKey.NET_QUANTITY.value)

    response = _evaluate(client, completed_run)

    assert response.status_code == 201
    assert response.json()["result"] == ComplianceCheck.Result.NON_COMPLIANT


def test_the_detail_endpoint_still_returns_the_full_trace(
    client, completed_run, make_rule
):
    make_rule("HIST-DETAIL", field_key=LabelFieldKey.NET_QUANTITY.value)
    created = _evaluate(client, completed_run).json()

    response = client.get(reverse("v1:compliance-detail", kwargs={"pk": created["id"]}))

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]
    assert body["findings"]
    assert body["violations"]
    assert body["extraction"]["id"] == str(completed_run.pk)


def test_an_unknown_id_on_the_detail_endpoint_is_still_a_404(client):
    response = client.get(reverse("v1:compliance-detail", kwargs={"pk": uuid.uuid4()}))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
