"""What `DEMO_PUBLIC_ANALYSIS_API` opens, and what it must never open.

`IsAuthenticatedOrDemoPublic` is asserted in both positions by the tests beside
each endpoint it guards - `apps/compliance/tests/test_analysis_api.py` and the
five suites with it. Those prove each endpoint behaves. None of them prove the
*set*: that turning the switch on opens these endpoints and no others.

That set is the whole security argument for running a public demonstration, and
it is stated in three places a reader trusts - `config/settings.py`,
`.env.example` and `docs/deployment.md`. A statement about a demo's blast radius
that nothing checks is a statement that drifts, and it had: all three said the
switch opened "two endpoints" while it guarded six. Asserting the surface here
means the next endpoint added with this permission class fails a test naming the
documents to update, rather than silently widening a public deployment.
"""

from __future__ import annotations

import pytest
from django.urls import get_resolver, reverse
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle

from apps.core.api.permissions import IsAuthenticatedOrDemoPublic

#: Every route the demo switch opens to anonymous callers, as the frontend's
#: workflow needs them: declare, upload, read, evaluate, retrieve. Changing this
#: list changes what a public demonstration exposes - update the three documents
#: named in the module docstring in the same commit.
DEMO_ROUTES = {
    "api/v1/images/",
    "api/v1/extraction/",
    "api/v1/compliance/",
    "api/v1/compliance/applicability-conditions/",
    "api/v1/compliance/<uuid:pk>/",
}

#: Deliberately public whether the switch is on or off. The health endpoint is
#: what a frontend and a platform health check call before anything else; the
#: catch-all turns an unmatched API path into the JSON error envelope.
ALWAYS_PUBLIC_ROUTES = {
    "api/v1/health/",
    "api/v1/^.*$",
}


def _api_views() -> dict[str, type]:
    """Every routed API view, keyed by its full URL pattern."""
    found: dict[str, type] = {}

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            path = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                walk(pattern, path)
                continue
            view = getattr(pattern.callback, "cls", None)
            if view is not None and path.startswith("api/"):
                found[path] = view

    walk(get_resolver())
    return found


def _permissions(view: type) -> set[type]:
    return set(getattr(view, "permission_classes", []))


def test_the_demo_switch_opens_exactly_these_endpoints():
    """The blast radius of a public demonstration, pinned."""
    guarded = {
        path
        for path, view in _api_views().items()
        if IsAuthenticatedOrDemoPublic in _permissions(view)
    }

    assert guarded == DEMO_ROUTES


def test_no_api_endpoint_is_unconditionally_public_except_the_two_that_must_be():
    """`AllowAny` stays a decision somebody made, not a default that spread."""
    public = {
        path
        for path, view in _api_views().items()
        if AllowAny in _permissions(view)
    }

    assert public == ALWAYS_PUBLIC_ROUTES


def test_every_other_api_endpoint_denies_by_default():
    """Anything not named above inherits `IsAuthenticated` and keeps it.

    The project's rule is that an endpoint is protected unless it opts out. An
    endpoint that opted out via neither list has opted out of nothing, which is
    what this asserts rather than assumes.
    """
    for path, view in _api_views().items():
        if path in DEMO_ROUTES or path in ALWAYS_PUBLIC_ROUTES:
            continue
        assert _permissions(view) == set(), (
            f"{path} sets its own permission_classes; if that is deliberate, "
            f"add it to one of the lists in this module and to the demo "
            f"documentation."
        )


@pytest.mark.django_db
def test_the_demo_switch_does_not_open_the_django_admin(client, settings):
    """The switch is a DRF permission class. Admin has never been in its reach.

    Asserted anyway: "the demo flag is on" must never be an answer to "how did
    someone reach the admin site", and a public deployment is exactly where
    that question gets asked.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True

    response = client.get("/admin/", follow=False)

    assert response.status_code in (301, 302)
    assert "login" in response["Location"]


@pytest.mark.django_db
def test_the_demo_surface_is_still_rate_limited(client, settings, monkeypatch):
    """Anonymous does not mean unmetered.

    The demonstration's only defence against someone pointing a script at it is
    the anonymous throttle, so the switch opening an endpoint must not be the
    thing that takes the throttle off it. The rate is lowered here rather than
    sending thirty requests: what is under test is that the throttle applies to
    a demo-opened endpoint, not the number in `API_THROTTLE_ANON`.
    """
    settings.DEMO_PUBLIC_ANALYSIS_API = True
    # Set where DRF actually reads it. `SimpleRateThrottle.THROTTLE_RATES` is
    # bound to the settings dict when the class body runs, so an override of
    # REST_FRAMEWORK here would change a dict the throttle no longer consults
    # and this test would pass against a deployment with throttling switched
    # off entirely. monkeypatch restores it.
    monkeypatch.setitem(AnonRateThrottle.THROTTLE_RATES, "anon", "2/min")
    url = reverse("v1:applicability-conditions")

    statuses = [client.get(url).status_code for _ in range(4)]

    assert statuses[0] == 200
    assert 429 in statuses, statuses
    assert client.get(url).json()["error"]["code"] == "rate_limited"
