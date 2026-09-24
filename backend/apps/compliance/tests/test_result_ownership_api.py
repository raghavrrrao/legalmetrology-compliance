"""Who may read a stored compliance result.

The question this file exists to answer is a single one, and it is the one the
analysis API got wrong until now:

    **can user A read user B's stored result?**

Reaching the endpoint and being entitled to the row are two different
permissions, and the project only ever had the first. `IsAuthenticatedOrDemoPublic`
answered "may this caller reach the analysis API?"; nothing answered "is this
result theirs?". A `ComplianceCheck` is a submission about a real package - the
photograph, what was read off it, and a legal conclusion drawn about it - so
"any caller who gets through can read any stored result" was a disclosure of
other people's work, not a rough edge in a list view.

`CallerScopedCheckQuerysetMixin` in `apps/compliance/api/views.py` is the fix.
It is one filter, so the tests that matter are not about its implementation but
about the four cases it has to get right, and each has its own section below:

    A reads A's           -> 200
    A reads B's           -> 404, and indistinguishable from a missing row
    anonymous / demo      -> only the anonymous demonstration pool
    unknown id            -> 404 in the standard envelope, no leak either way

The detail endpoint and the history list are asserted **side by side
throughout**. They are two doors onto the same rows and they were both open;
fixing one and leaving the other is the failure mode these tests exist to
prevent, and it is why no case here checks only one of them.

Both are exercised at the HTTP layer with a real session, not by calling
`scope_to_caller` directly. A queryset that filters correctly and a view that
forgets to use it look identical from underneath.

Checks are built directly rather than through the engine: what is under test is
who may read a row, and producing a genuine verdict first would only add a
second thing that could fail. Verdicts have their own suites.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.compliance.models import ComplianceCheck

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_user(db):
    """A second real account, so "somebody else" is a user and not a null.

    The `user` fixture in `conftest.py` is the caller throughout this file;
    this is the person whose results they must not be able to read.
    """
    return get_user_model().objects.create_user(
        username="someone-else", password="not-a-real-password"
    )


@pytest.fixture
def make_check(db, completed_run):
    """A stored `ComplianceCheck` owned by whoever is passed in.

    `requested_by=None` is the anonymous demonstration case and is spelled out
    at each call site rather than defaulted, because in this file who owns a
    row is the entire subject and an implicit owner would be the one detail a
    reader has to go and look up.
    """

    def _make(requested_by, **kwargs) -> ComplianceCheck:
        return ComplianceCheck.objects.create(
            extraction_run=completed_run,
            product=completed_run.image.product,
            requested_by=requested_by,
            status=ComplianceCheck.Status.COMPLETED,
            result=kwargs.pop("result", ComplianceCheck.Result.REVIEW_REQUIRED),
            engine_version=kwargs.pop("engine_version", "test-1.0"),
            **kwargs,
        )

    return _make


def _detail(client, check_id):
    return client.get(reverse("v1:compliance-detail", kwargs={"pk": check_id}))


def _history(client):
    return client.get(reverse("v1:compliance-evaluate"))


def _listed_ids(response) -> set[str]:
    return {row["id"] for row in response.json()["results"]}


# --- A reads A's own result ---------------------------------------------------


def test_a_user_can_read_their_own_result(client, user, make_check):
    """The case that must keep working. Scoping that also locks out the owner
    is not a fix, it is an outage."""
    mine = make_check(requested_by=user)
    client.force_login(user)

    response = _detail(client, mine.pk)

    assert response.status_code == 200
    assert response.json()["id"] == str(mine.pk)


def test_a_user_lists_their_own_results(client, user, make_check):
    mine = make_check(requested_by=user)
    client.force_login(user)

    response = _history(client)

    assert response.status_code == 200
    assert _listed_ids(response) == {str(mine.pk)}


# --- A reads B's result -------------------------------------------------------


def test_a_user_cannot_read_another_users_result(
    client, user, other_user, make_check
):
    """The vulnerability, asserted as closed.

    Holding the id is the whole of what the old API asked for. Here the caller
    is given the id outright - `theirs.pk` is read straight from the row - so
    the test cannot pass by the id merely being hard to guess.
    """
    theirs = make_check(requested_by=other_user)
    client.force_login(user)

    response = _detail(client, theirs.pk)

    assert response.status_code == 404


def test_another_users_result_is_absent_from_the_history(
    client, user, other_user, make_check
):
    """The list must not hand out what the detail endpoint refuses."""
    theirs = make_check(requested_by=other_user)
    mine = make_check(requested_by=user)
    client.force_login(user)

    response = _history(client)

    assert _listed_ids(response) == {str(mine.pk)}
    assert str(theirs.pk) not in _listed_ids(response)
    assert response.json()["count"] == 1


def test_the_owner_of_that_same_result_can_still_read_it(
    client, user, other_user, make_check
):
    """The refusal above is about *who is asking*, not about the row.

    Without this pairing, a view that 404s for everybody would satisfy the
    test above and nobody would notice until a user could not open their own
    result.
    """
    theirs = make_check(requested_by=other_user)

    client.force_login(user)
    denied = _detail(client, theirs.pk)
    client.force_login(other_user)
    allowed = _detail(client, theirs.pk)

    assert denied.status_code == 404
    assert allowed.status_code == 200
    assert allowed.json()["id"] == str(theirs.pk)


def test_another_users_result_is_indistinguishable_from_one_that_does_not_exist(
    client, user, other_user, make_check
):
    """404 and not 403, deliberately.

    A 403 says "this id names a real result, and it is not yours" - which
    confirms the existence of somebody else's submission to a caller who has no
    business establishing it, and turns the endpoint into an oracle for
    checking ids. The two responses are compared field by field rather than by
    status alone, because a body that differed would leak exactly what the
    status code was chosen to withhold.
    """
    theirs = make_check(requested_by=other_user)
    client.force_login(user)

    forbidden = _detail(client, theirs.pk)
    missing = _detail(client, uuid.uuid4())

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


# --- anonymous and the demonstration pool -------------------------------------


def test_anonymous_reaches_nothing_with_the_demo_switch_off(
    client, user, make_check, settings
):
    """Deny-by-default is unchanged, and it is still the shipped position."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    mine = make_check(requested_by=user)

    detail = _detail(client, mine.pk)
    history = _history(client)

    assert detail.status_code in (401, 403)
    assert history.status_code in (401, 403)


def test_the_demo_caller_can_read_the_demo_result(client, make_check, settings):
    """The SIH flow: upload anonymously, then open the result by its link.

    This is what stops the fix from being scoping that breaks the
    demonstration. An anonymous check has no owner to match a caller against,
    so anonymous callers share one pool - documented on the mixin, and the
    reason the switch defaults to off.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    demo = make_check(requested_by=None)

    detail = _detail(client, demo.pk)
    history = _history(client)

    assert detail.status_code == 200
    assert detail.json()["id"] == str(demo.pk)
    assert _listed_ids(history) == {str(demo.pk)}


def test_the_demo_caller_cannot_read_a_signed_in_users_result(
    client, user, make_check, settings
):
    """The exposure that actually mattered.

    With the demonstration switch on, anonymous is the *least* authenticated
    caller the API has, and before scoping it could read every stored result on
    the deployment. A user's submission must be invisible to it - by id and in
    the list alike.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    theirs = make_check(requested_by=user)
    demo = make_check(requested_by=None)

    detail = _detail(client, theirs.pk)
    history = _history(client)

    assert detail.status_code == 404
    assert _listed_ids(history) == {str(demo.pk)}


def test_a_signed_in_user_does_not_inherit_the_demo_pool(
    client, user, make_check, settings
):
    """Scoping cuts both ways.

    An authenticated caller sees their own work, which does not include the
    anonymous pool - otherwise logging in would be a way to widen access rather
    than to claim a result, and every demonstration upload would appear in the
    history of the next person to sign in.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    demo = make_check(requested_by=None)
    mine = make_check(requested_by=user)
    client.force_login(user)

    assert _detail(client, demo.pk).status_code == 404
    assert _listed_ids(_history(client)) == {str(mine.pk)}


# --- unknown and malformed ids ------------------------------------------------


def test_an_unknown_id_is_a_404_in_the_standard_envelope(
    client, user, make_check
):
    """A safe response for a row that was never there.

    Asserted with a stored check present, so the 404 is the scoping and the
    lookup agreeing rather than an empty table answering by accident.
    """
    make_check(requested_by=user)
    client.force_login(user)

    response = _detail(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_an_id_that_is_not_a_uuid_does_not_reach_the_view(client, user):
    """The URL converter rejects it, so no query is built from caller input."""
    client.force_login(user)

    response = client.get("/api/v1/compliance/not-a-uuid/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- the write path is unaffected ---------------------------------------------


def test_a_users_own_evaluation_is_readable_immediately_afterwards(
    client, user, completed_run, make_rule
):
    """POST then GET, as a client actually does it.

    The end-to-end version of the first test in this file: the check is created
    through the API with a real logged-in session rather than assembled in the
    fixture, so `requested_by` being recorded on the write path and filtered on
    the read path are shown to agree. A mismatch there would leave every user
    unable to open the result they had just been handed.
    """
    make_rule("OWN-POST")
    # The reading is theirs too, as `POST /api/v1/extraction/` records it: a
    # signed-in user may evaluate only runs whose photographs they uploaded
    # (`test_run_ownership_api.py`), and the fixture's image has no uploader.
    completed_run.image.uploaded_by = user
    completed_run.image.save(update_fields=["uploaded_by"])
    client.force_login(user)

    created = client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": str(completed_run.pk)},
        content_type="application/json",
    )
    assert created.status_code == 201

    fetched = _detail(client, created.json()["id"])

    assert fetched.status_code == 200
    assert fetched.json()["id"] == created.json()["id"]
    assert ComplianceCheck.objects.get().requested_by_id == user.pk
