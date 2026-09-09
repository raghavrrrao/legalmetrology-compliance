"""HTTPS redirect behaviour, and the API's trailing-slash convention.

Why this file exists
--------------------
CI ran the backend with `DJANGO_DEBUG=False`, which turns on
`SECURE_SSL_REDIRECT`. SecurityMiddleware then answered every test-client
request with `301 -> https://testserver/...`, and five tests in
test_health.py / test_error_envelope.py failed. Locally `DJANGO_DEBUG=True`,
so the setting was never applied and the same tests passed.

The failure looks like a URL-routing problem and is not one. The two redirects
have completely different signatures, and confusing them sends you to the wrong
file:

    SECURE_SSL_REDIRECT   301  Location: https://testserver/api/v1/compliance/
                               absolute URL, scheme changed, path UNCHANGED

    APPEND_SLASH          301  Location: /admin/
                               relative URL, path changed, scheme UNCHANGED

`conftest.py` disables the SSL redirect for the suite, because the test client
is not a browser. These tests then assert the real behaviour directly, so the
production guarantee stays covered rather than being lost with it.

One path is deliberately exempt from the redirect - `/api/v1/health/`, so a
deployment platform's plain-HTTP health probe is answered rather than
redirected. That exemption is a deployment requirement with a security cost, so
it is asserted in both directions below: the health path must not redirect, and
everything else must.
"""

import pytest
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


# --- what CI was actually failing on ----------------------------------------


def test_api_answers_plain_http_in_tests(client):
    """The regression itself: a plain-HTTP test request must reach the view.

    This is what returned 301 in CI. It passes locally either way, so it only
    guards the failure in combination with the conftest fixture - which is the
    point: the suite must not depend on DJANGO_DEBUG.
    """
    response = client.get(reverse("v1:health"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")


def test_suite_runs_without_the_ssl_redirect(settings):
    """The autouse fixture in conftest.py is doing its job.

    If someone removes it, this fails immediately with a clear reason rather
    than as five confusing 301s elsewhere.
    """
    assert settings.SECURE_SSL_REDIRECT is False


# --- the production guarantee, asserted directly -----------------------------


#: A path the redirect must apply to. Any API path outside the health check
#: would do; this one is used because it exists, is routed, and needs no
#: fixtures - SecurityMiddleware answers before authentication is ever reached,
#: so the 403 it would otherwise return never happens.
REDIRECTED_PATH = "/api/v1/compliance/"


def test_ssl_redirect_still_works_when_enabled():
    """Turning the setting on must genuinely redirect HTTP to HTTPS.

    Disabling it for the suite would be hiding a bug if the redirect no longer
    worked, so it is exercised here on purpose. This is the deployment
    behaviour: `SECURE_SSL_REDIRECT` defaults to True whenever DEBUG is False.

    A fresh `Client` is built INSIDE the override because SecurityMiddleware
    reads `SECURE_SSL_REDIRECT` once, when the middleware chain is loaded. A
    client created before the override keeps the old value and this test would
    pass for the wrong reason.
    """
    with override_settings(SECURE_SSL_REDIRECT=True):
        response = Client().get(REDIRECTED_PATH)

    assert response.status_code == 301
    assert response["Location"] == "https://testserver" + REDIRECTED_PATH


def test_ssl_redirect_preserves_the_path_and_only_changes_the_scheme():
    """Pins the signature that distinguishes this from an APPEND_SLASH redirect.

    Whoever debugs the next 301 should be able to tell the two apart from the
    Location header alone.
    """
    with override_settings(SECURE_SSL_REDIRECT=True):
        response = Client().get(REDIRECTED_PATH)

    location = response["Location"]
    assert location.startswith("https://")
    assert location.endswith(REDIRECTED_PATH)
    # The path is untouched - no slash was added or removed.
    assert location == "https://testserver" + REDIRECTED_PATH


def test_https_requests_are_not_redirected_even_when_enabled():
    """Confirms the redirect is scheme-driven, not path-driven."""
    with override_settings(SECURE_SSL_REDIRECT=True):
        response = Client().get(REDIRECTED_PATH, secure=True)

    assert response.status_code != 301


# --- the one path the redirect must not apply to -----------------------------


def test_the_health_endpoint_is_exempt_from_the_ssl_redirect():
    """The deployment requirement, asserted rather than trusted to a setting.

    A platform health probe reaches the container over plain HTTP on an
    internal network and does not follow redirects. With the redirect applied
    to this path, every probe gets a 301, the health check never passes, and
    the deployment is rolled back with an error that names neither HTTPS nor
    the health check.

    `SECURE_REDIRECT_EXEMPT` in config/settings.py is what prevents that. This
    test is the reason it may not later be removed as dead configuration.
    """
    with override_settings(SECURE_SSL_REDIRECT=True):
        response = Client().get(reverse("v1:health"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")


def test_the_exemption_covers_only_the_health_endpoint():
    """The exemption is one exact path, not a prefix and not a pattern.

    Written down because the cost of getting this wrong is asymmetric: an
    over-broad pattern here silently stops enforcing HTTPS on real endpoints,
    and nothing else in the suite would notice.
    """
    with override_settings(SECURE_SSL_REDIRECT=True):
        client = Client()
        # A path that merely starts the same way is not exempt.
        assert client.get("/api/v1/health/extra/").status_code == 301
        assert client.get(REDIRECTED_PATH).status_code == 301


def test_the_health_endpoint_over_https_is_unchanged_by_the_exemption():
    """The exemption must not turn into a downgrade.

    It stops a redirect from being issued; it does not stop the endpoint from
    working over HTTPS, which is how every browser will reach it.
    """
    with override_settings(SECURE_SSL_REDIRECT=True):
        response = Client().get(reverse("v1:health"), secure=True)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")


# --- the URL convention ------------------------------------------------------


#: Stand-in values for reversing a route that takes path parameters. Keyed by
#: Django's converter class name, because that is what the resolver records.
#: The values are never fetched - they exist only so `reverse()` can build a
#: URL to check the shape of.
_SAMPLE_ARGUMENT_BY_CONVERTER = {
    "UUIDConverter": "00000000-0000-0000-0000-000000000000",
    "IntConverter": "1",
    "SlugConverter": "sample",
    "StringConverter": "sample",
    "PathConverter": "sample",
}


def test_api_routes_use_trailing_slashes():
    """The documented convention (docs/api.md): every API route ends in '/'.

    Asserted over the resolved URLconf rather than a hand-written list, so a
    route added later without a trailing slash fails here instead of producing
    a silent redirect that turns a POST into a GET.

    Routes that take path parameters are reversed with a stand-in value for
    each. Reversing them with no arguments - as this test originally did, when
    every route was argument-less - raises `NoReverseMatch`, which would have
    made the first parameterised endpoint in the project look like a broken
    route rather than an unhandled case in the test.
    """
    from django.urls import get_resolver

    # Namespaced routes live in namespace_dict, not the root reverse_dict.
    _, v1_resolver = get_resolver().namespace_dict["v1"]

    names = [key for key in v1_resolver.reverse_dict if isinstance(key, str)]
    assert names, "no v1 routes found - the namespace may have changed"

    for name in names:
        # The catch-all 404 route is a regex matching any suffix, so reversing
        # it needs an argument and it is not a real endpoint anyway.
        if name == "not-found":
            continue

        converters = v1_resolver.reverse_dict[name][3]
        kwargs = {}
        for parameter, converter in converters.items():
            sample = _SAMPLE_ARGUMENT_BY_CONVERTER.get(type(converter).__name__)
            assert sample is not None, (
                f"route {name!r} uses path converter "
                f"{type(converter).__name__!r}, which this test has no sample "
                f"value for - add one to _SAMPLE_ARGUMENT_BY_CONVERTER"
            )
            kwargs[parameter] = sample

        url = reverse(f"v1:{name}", kwargs=kwargs)
        assert url.endswith("/"), f"API route {name!r} -> {url!r} lacks a trailing slash"
        assert url.startswith("/api/v1/"), f"{name!r} -> {url!r} is outside /api/v1/"


def test_health_route_matches_the_documented_path():
    assert reverse("v1:health") == "/api/v1/health/"
