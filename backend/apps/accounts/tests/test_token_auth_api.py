"""API authentication: `POST /auth/login/`, `POST /auth/logout/`, `GET /auth/me/`,
and `Authorization: Bearer <token>` on every other endpoint.

Everything goes over HTTP with the real header - the helpers in
`apps.accounts.tokens` are reached only through the endpoints and the
authentication class, as a client reaches them. What is pinned:

    login          valid, wrong, unknown, inactive, malformed - and no username
                   can be told to exist from the response
    the token      opaque, stored only as a hash, one per login, revocable one
                   at a time, expiring on the configured lifetime
    the header     missing, malformed, foreign scheme, unknown, revoked,
                   expired, inactive owner - each with the right status
    secrecy        the token and password in no log line and no error body
    throttling     per client and per account, and the account limit survives
                   a spoofed X-Forwarded-For
    what did not change - anonymous demo analysis, the 403 an existing client
                   sees without credentials, admin and session login, CSRF on
                   session requests, and ownership of analysis results
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.api.throttles import LoginAccountRateThrottle, LoginClientRateThrottle
from apps.accounts.models import ApiToken
from apps.compliance.models import ComplianceCheck
from apps.extraction.models import ExtractionRun

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple-7"
TOKEN_RE = re.compile(r"^lmt_[A-Za-z0-9_-]{43}$")


@pytest.fixture
def account(db):
    return get_user_model().objects.create_user(
        username="inspector", password=PASSWORD, email="inspector@example.test",
        first_name="Asha", last_name="Rao",
    )


@pytest.fixture
def other_account(db):
    return get_user_model().objects.create_user(username="other-inspector", password=PASSWORD)


def _login(client: Client, username: str = "inspector", password: str = PASSWORD, **extra):
    return client.post(
        reverse("v1:auth-login"),
        {"username": username, "password": password},
        content_type="application/json",
        **extra,
    )


def _token_for(client: Client, username: str = "inspector") -> str:
    response = _login(client, username)
    assert response.status_code == 201, response.content
    return response.json()["token"]


def _bearer(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _me(client: Client, **headers):
    return client.get(reverse("v1:auth-me"), **headers)


def _logout(client: Client, **headers):
    return client.post(reverse("v1:auth-logout"), **headers)


def _assert_token_rejected(response) -> None:
    """A rejected Bearer token: 401, a Bearer challenge, one generic message."""
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "authentication_failed",
        "message": "Invalid or expired token.",
        "details": None,
    }
    assert response["WWW-Authenticate"].startswith("Bearer ")


# --- login ------------------------------------------------------------------------


def test_a_valid_login_returns_a_token_once_and_the_account(client, account):
    response = _login(client)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"token", "token_type", "expires_at", "user"}
    assert TOKEN_RE.fullmatch(body["token"])
    assert body["token_type"] == "Bearer"
    assert body["user"] == {
        "id": account.pk,
        "username": "inspector",
        "email": "inspector@example.test",
        "first_name": "Asha",
        "last_name": "Rao",
    }
    stored = ApiToken.objects.get()
    assert stored.user == account
    assert parse_datetime(body["expires_at"]) == stored.expires_at
    account.refresh_from_db()
    assert account.last_login is not None


def test_a_wrong_password_is_refused_without_issuing_anything(client, account):
    response = _login(client, password="not-the-password")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert not ApiToken.objects.exists()


def test_an_unknown_username_is_indistinguishable_from_a_wrong_password(client, account):
    """No response difference that would reveal which usernames exist."""
    wrong_password = _login(client, password="not-the-password")
    unknown_user = _login(client, username="nobody-by-this-name")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_an_inactive_account_cannot_log_in_and_looks_like_bad_credentials(client, account):
    account.is_active = False
    account.save(update_fields=["is_active"])

    response = _login(client)

    assert response.status_code == 401
    assert response.json() == _login(client, password="not-the-password").json()
    assert not ApiToken.objects.exists()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "inspector"},
        {"password": PASSWORD},
        {"username": "", "password": PASSWORD},
        {"username": ["inspector"], "password": PASSWORD},
    ],
)
def test_a_malformed_login_is_a_validation_error(client, account, body):
    response = client.post(reverse("v1:auth-login"), body, content_type="application/json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert not ApiToken.objects.exists()


def test_a_login_body_that_is_not_json_is_a_parse_error(client, account):
    response = client.post(reverse("v1:auth-login"), "{not json", content_type="application/json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "parse_error"


def test_login_accepts_get_only_as_a_405(client):
    response = client.get(reverse("v1:auth-login"))

    assert response.status_code == 405


def test_a_stale_token_in_the_header_does_not_stop_a_new_login(client, account):
    token = _token_for(client)
    ApiToken.objects.update(revoked_at=timezone.now())

    response = _login(client, **_bearer(token))

    assert response.status_code == 201


# --- the Bearer header ----------------------------------------------------------


def test_a_bearer_token_authenticates_the_request(client, account):
    token = _token_for(client)

    response = _me(client, **_bearer(token))

    assert response.status_code == 200
    assert response.json()["username"] == "inspector"


def test_the_scheme_name_is_case_insensitive(client, account):
    token = _token_for(client)

    assert _me(client, HTTP_AUTHORIZATION=f"bearer {token}").status_code == 200


def test_no_authorization_header_is_the_same_403_as_before_tokens_existed(client, account):
    """Existing clients send no credentials and branch on 403; that is unchanged."""
    response = _me(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert "WWW-Authenticate" not in response


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer ",
        "Bearer lmt_abc def",
        "Bearer not-one-of-our-tokens",
        "Bearer lmt_" + "a" * 42,
        "Bearer lmt_" + "a" * 44,
        "Bearer lmt_" + "a" * 42 + "!",
        "Bearer lmt_" + "é" * 43,
    ],
)
def test_a_malformed_bearer_header_is_rejected(client, account, header):
    response = client.get(reverse("v1:auth-me"), HTTP_AUTHORIZATION=header)

    _assert_token_rejected(response)


@pytest.mark.parametrize("header", ["Basic aW5zcGVjdG9yOnB3", "Token abc", "Digest x"])
def test_another_scheme_is_not_ours_and_counts_as_no_credentials(client, header):
    response = client.get(reverse("v1:auth-me"), HTTP_AUTHORIZATION=header)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


def test_a_well_formed_but_unknown_token_is_rejected(client, account):
    _token_for(client)

    _assert_token_rejected(_me(client, **_bearer("lmt_" + "A" * 43)))


def test_a_revoked_token_is_rejected(client, account):
    token = _token_for(client)
    ApiToken.objects.update(revoked_at=timezone.now())

    _assert_token_rejected(_me(client, **_bearer(token)))


def test_an_expired_token_is_rejected(client, account):
    token = _token_for(client)
    ApiToken.objects.update(expires_at=timezone.now() - datetime.timedelta(seconds=1))

    _assert_token_rejected(_me(client, **_bearer(token)))


def test_a_token_stops_working_when_its_account_is_deactivated(client, account):
    token = _token_for(client)
    assert _me(client, **_bearer(token)).status_code == 200

    account.is_active = False
    account.save(update_fields=["is_active"])

    _assert_token_rejected(_me(client, **_bearer(token)))


def test_every_rejection_reads_the_same(client, account):
    """Unknown, revoked, expired and deactivated are indistinguishable outside."""
    tokens = [_token_for(client) for _ in range(3)]
    rows = list(ApiToken.objects.order_by("created_at", "id"))
    rows[0].revoked_at = timezone.now()
    rows[0].save()
    rows[1].expires_at = timezone.now() - datetime.timedelta(minutes=1)
    rows[1].save()
    bodies = {
        str(_me(client, **_bearer(tokens[0])).json()),
        str(_me(client, **_bearer(tokens[1])).json()),
        str(_me(client, **_bearer("lmt_" + "B" * 43)).json()),
        str(_me(client, HTTP_AUTHORIZATION="Bearer garbage").json()),
    }

    assert len(bodies) == 1


def test_last_used_is_recorded_without_a_write_per_request(client, account):
    token = _token_for(client)
    assert ApiToken.objects.get().last_used_at is None

    _me(client, **_bearer(token))
    first = ApiToken.objects.get().last_used_at
    _me(client, **_bearer(token))

    assert first is not None
    assert ApiToken.objects.get().last_used_at == first


# --- me ---------------------------------------------------------------------------


def test_me_describes_the_account_and_nothing_sensitive(client, account):
    token = _token_for(client)

    body = _me(client, **_bearer(token)).json()

    assert body == {
        "id": account.pk,
        "username": "inspector",
        "email": "inspector@example.test",
        "first_name": "Asha",
        "last_name": "Rao",
    }
    for field in ("password", "is_staff", "is_superuser", "groups", "user_permissions", "last_login"):
        assert field not in body


@pytest.mark.parametrize("demo", [True, False])
def test_me_refuses_an_anonymous_caller_whatever_the_demo_switch(client, settings, demo):
    settings.DEMO_PUBLIC_ANALYSIS_API = demo

    response = _me(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


# --- logout -----------------------------------------------------------------------


def test_logout_revokes_the_token_it_was_called_with(client, account):
    token = _token_for(client)

    response = _logout(client, **_bearer(token))

    assert response.status_code == 204
    assert ApiToken.objects.get().revoked_at is not None


def test_a_logged_out_token_cannot_be_used_again_even_to_log_out(client, account):
    token = _token_for(client)
    assert _logout(client, **_bearer(token)).status_code == 204
    revoked_at = ApiToken.objects.get().revoked_at

    _assert_token_rejected(_me(client, **_bearer(token)))
    _assert_token_rejected(_logout(client, **_bearer(token)))
    # The second logout changed nothing: still revoked, at the same moment.
    assert ApiToken.objects.get().revoked_at == revoked_at


def test_logging_out_one_device_leaves_the_others_signed_in(client, account):
    phone = _token_for(client)
    laptop = _token_for(client)

    assert _logout(client, **_bearer(phone)).status_code == 204

    _assert_token_rejected(_me(client, **_bearer(phone)))
    assert _me(client, **_bearer(laptop)).status_code == 200
    assert ApiToken.objects.filter(revoked_at__isnull=True).count() == 1


def test_logout_without_a_token_is_refused(client, account):
    response = _logout(client)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


def test_logout_does_not_accept_a_session_as_a_token(client, account):
    """A session has no token to revoke; it is not told it logged out."""
    client.force_login(account)

    assert _logout(client).status_code == 403


# --- password changes -------------------------------------------------------------

NEW_PASSWORD = "a-different-password-entirely-4"


def _change_password(user, password: str) -> None:
    """How an administrator or a future reset flow changes it: set_password, save."""
    user.set_password(password)
    user.save()


def test_a_token_works_before_any_password_change(client, account):
    token = _token_for(client)

    assert _me(client, **_bearer(token)).status_code == 200


def test_changing_the_password_ends_a_token_issued_before_it(client, account):
    token = _token_for(client)
    assert _me(client, **_bearer(token)).status_code == 200

    _change_password(account, NEW_PASSWORD)

    # The same generic rejection as any other bad token - nothing says why.
    _assert_token_rejected(_me(client, **_bearer(token)))
    _assert_token_rejected(_logout(client, **_bearer(token)))


def test_the_token_is_refused_not_revoked(client, account):
    """The row is untouched: it stops matching the password, it is not rewritten."""
    token = _token_for(client)
    before = ApiToken.objects.values("revoked_at", "expires_at", "password_auth_hash").get()

    _change_password(account, NEW_PASSWORD)
    _assert_token_rejected(_me(client, **_bearer(token)))

    assert ApiToken.objects.values("revoked_at", "expires_at", "password_auth_hash").get() == before
    assert before["revoked_at"] is None


def test_a_token_issued_after_the_change_works(client, account):
    old = _token_for(client)
    _change_password(account, NEW_PASSWORD)

    assert _login(client).status_code == 401
    new = _login(client, password=NEW_PASSWORD).json()["token"]

    assert _me(client, **_bearer(new)).status_code == 200
    _assert_token_rejected(_me(client, **_bearer(old)))


def test_changing_the_password_back_does_not_revive_an_old_token(client, account):
    """Each stored password hash has a fresh salt, so the same password is a new hash."""
    token = _token_for(client)

    _change_password(account, NEW_PASSWORD)
    _assert_token_rejected(_me(client, **_bearer(token)))
    _change_password(account, PASSWORD)

    _assert_token_rejected(_me(client, **_bearer(token)))
    assert _me(client, **_bearer(_token_for(client))).status_code == 200


def test_a_password_change_ends_every_earlier_token_of_that_user_only(
    client, account, other_account
):
    phone = _token_for(client)
    laptop = _token_for(client)
    someone_else = _token_for(client, "other-inspector")

    _change_password(account, NEW_PASSWORD)

    _assert_token_rejected(_me(client, **_bearer(phone)))
    _assert_token_rejected(_me(client, **_bearer(laptop)))
    assert _me(client, **_bearer(someone_else)).status_code == 200


def test_the_recorded_hash_is_the_session_auth_hash_and_never_leaves_the_server(client, account):
    login = _login(client)
    token = login.json()["token"]
    stored = ApiToken.objects.get().password_auth_hash

    assert stored == account.get_session_auth_hash()
    assert PASSWORD not in stored and account.password not in stored
    assert stored not in login.content.decode()
    assert stored not in _me(client, **_bearer(token)).content.decode()


def test_rotating_secret_key_with_a_fallback_keeps_tokens_and_moves_them_on(
    client, account, settings
):
    """As with sessions: a key in SECRET_KEY_FALLBACKS still verifies the token."""
    token = _token_for(client)
    old_key = settings.SECRET_KEY
    settings.SECRET_KEY = "rotated-" + old_key
    settings.SECRET_KEY_FALLBACKS = [old_key]

    assert _me(client, **_bearer(token)).status_code == 200
    # Moved onto the current key, so the fallback can later be dropped.
    assert ApiToken.objects.get().password_auth_hash == account.get_session_auth_hash()
    settings.SECRET_KEY_FALLBACKS = []
    assert _me(client, **_bearer(token)).status_code == 200


def test_rotating_secret_key_without_a_fallback_ends_tokens(client, account, settings):
    """The session-auth hash is keyed with SECRET_KEY; a new key is a new hash."""
    token = _token_for(client)
    settings.SECRET_KEY = "rotated-" + settings.SECRET_KEY
    settings.SECRET_KEY_FALLBACKS = []

    _assert_token_rejected(_me(client, **_bearer(token)))


def test_sessions_still_end_on_a_password_change_as_django_makes_them(client, account):
    """Session authentication is unchanged, including its own invalidation."""
    client.force_login(account)
    assert _me(client).status_code == 200

    _change_password(account, NEW_PASSWORD)

    response = _me(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


# --- storage ----------------------------------------------------------------------


def test_each_login_issues_a_distinct_token_and_all_of_them_work(client, account):
    tokens = [_token_for(client) for _ in range(3)]

    assert len(set(tokens)) == 3
    assert ApiToken.objects.filter(user=account).count() == 3
    assert len(set(ApiToken.objects.values_list("token_hash", flat=True))) == 3
    for token in tokens:
        assert _me(client, **_bearer(token)).status_code == 200


def test_only_a_hash_of_the_token_is_stored(client, account):
    token = _token_for(client)
    row = ApiToken.objects.get()

    assert row.token_hash == hashlib.sha256(token.encode("ascii")).hexdigest()
    assert token not in row.token_hash
    stored = [str(value) for value in ApiToken.objects.values().get().values()]
    assert all(token not in value and token[4:] not in value for value in stored)


def test_a_new_token_lasts_the_configured_lifetime(client, account, settings):
    settings.API_TOKEN_LIFETIME_HOURS = 2
    before = timezone.now()

    response = _login(client)

    expires = ApiToken.objects.get().expires_at
    lifetime = datetime.timedelta(hours=2)
    assert before + lifetime <= expires <= timezone.now() + lifetime
    assert parse_datetime(response.json()["expires_at"]) == expires


def test_the_lifetime_is_measured_from_issue_and_not_extended_by_use(client, account):
    token = _token_for(client)
    expires = ApiToken.objects.get().expires_at

    for _ in range(3):
        _me(client, **_bearer(token))

    assert ApiToken.objects.get().expires_at == expires


# --- secrecy ----------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())
        if record.exc_info:
            self.lines.append(logging.Formatter().formatException(record.exc_info))


@pytest.fixture
def captured_logs():
    """Every configured logger at DEBUG, directly.

    `apps` and `django` do not propagate to the root (config/settings.py), so a
    root-level capture would see nothing and prove nothing. The handler goes on
    each of them instead.
    """
    handler = _Capture()
    names = ["", "apps", "django", "django.request", "django.server", "rest_framework", "labelextract"]
    loggers = [logging.getLogger(name) for name in names]
    previous = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
    yield handler
    for lg, level in previous:
        lg.removeHandler(handler)
        lg.setLevel(level)


def test_the_token_and_password_appear_in_no_log_line_and_no_error_body(
    client, account, captured_logs
):
    login = _login(client)
    token = login.json()["token"]
    bodies = [
        _me(client, **_bearer(token)).content.decode(),
        _login(client, password="wrong-" + PASSWORD).content.decode(),
        _me(client, HTTP_AUTHORIZATION=f"Bearer {token}x").content.decode(),
        _logout(client, **_bearer(token)).content.decode(),
        _me(client, **_bearer(token)).content.decode(),
        _logout(client, **_bearer(token)).content.decode(),
    ]

    text = "\n".join(captured_logs.lines)
    assert "Issued API token" in text, "the capture saw nothing - the test would be vacuous"
    for secret in (token, token[4:], PASSWORD):
        assert secret not in text
        for body in bodies:
            assert secret not in body
    # Only the login response carries the token, and only once.
    assert login.content.decode().count(token) == 1


# --- throttling -------------------------------------------------------------------


def test_login_is_throttled_per_client(client, account, monkeypatch):
    monkeypatch.setitem(LoginClientRateThrottle.THROTTLE_RATES, "auth_login", "3/min")

    statuses = [_login(client, password="wrong").status_code for _ in range(3)]
    blocked = _login(client)

    assert statuses == [401, 401, 401]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["details"]["retry_after_seconds"] > 0
    assert not ApiToken.objects.exists()


def test_login_is_throttled_per_account_whatever_the_client_address(client, account, monkeypatch):
    """The per-client limit can be dodged by varying X-Forwarded-For; this cannot."""
    monkeypatch.setitem(LoginAccountRateThrottle.THROTTLE_RATES, "auth_login_account", "3/hour")

    statuses = [
        _login(
            client,
            username=username,
            password="wrong",
            REMOTE_ADDR=f"203.0.113.{n}",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{n}",
        ).status_code
        for n, username in enumerate(["inspector", "INSPECTOR", "Inspector"], start=1)
    ]
    blocked = _login(client, REMOTE_ADDR="203.0.113.99", HTTP_X_FORWARDED_FOR="198.51.100.99")

    assert statuses == [401, 401, 401]
    assert blocked.status_code == 429
    assert not ApiToken.objects.exists()


def test_the_account_throttle_does_not_affect_another_account(
    client, account, other_account, monkeypatch
):
    monkeypatch.setitem(LoginAccountRateThrottle.THROTTLE_RATES, "auth_login_account", "2/hour")
    for _ in range(2):
        _login(client, password="wrong")

    assert _login(client).status_code == 429
    assert _login(client, username="other-inspector").status_code == 201


def _account_bucket(username: str) -> str:
    """The cache key the per-account throttle would use for `username`."""
    digest = hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()
    return LoginAccountRateThrottle.cache_format % {
        "scope": LoginAccountRateThrottle.scope,
        "ident": digest,
    }


@pytest.fixture
def numeric_account(db):
    """A real account whose username is all digits - an employee number, say."""
    return get_user_model().objects.create_user(username="12345", password=PASSWORD)


def test_a_numeric_json_username_is_throttled_per_account(client, numeric_account, monkeypatch):
    """`{"username": 12345}` signs in as "12345", so it must count against it.

    It used to be skipped by the per-account throttle - which keyed only on a
    string - while the serializer still accepted the number and checked the
    password: unlimited guessing, with the address varied as well.
    """
    monkeypatch.setitem(LoginAccountRateThrottle.THROTTLE_RATES, "auth_login_account", "3/hour")

    statuses = [
        _login(
            client,
            username=12345,
            password="wrong",
            REMOTE_ADDR=f"203.0.113.{n}",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{n}",
        ).status_code
        for n in range(1, 4)
    ]
    blocked = _login(
        client, username=12345, REMOTE_ADDR="203.0.113.99", HTTP_X_FORWARDED_FOR="198.51.100.99"
    )

    assert statuses == [401, 401, 401]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert not ApiToken.objects.exists()


def test_a_numeric_and_a_string_username_share_one_bucket(client, numeric_account, monkeypatch):
    """12345 and "12345" are one account, so alternating them buys nothing."""
    monkeypatch.setitem(LoginAccountRateThrottle.THROTTLE_RATES, "auth_login_account", "3/hour")

    statuses = [
        _login(client, username=username, password="wrong", REMOTE_ADDR=f"203.0.113.{n}").status_code
        for n, username in enumerate([12345, "12345", 12345], start=1)
    ]

    assert statuses == [401, 401, 401]
    assert _login(client, username="12345", REMOTE_ADDR="203.0.113.50").status_code == 429
    assert _login(client, username=12345, REMOTE_ADDR="203.0.113.51").status_code == 429
    assert not ApiToken.objects.exists()


def test_a_numeric_username_still_signs_in_under_the_limit(client, numeric_account):
    """Counting numbers is not refusing them: under the limit, 12345 logs in."""
    response = _login(client, username=12345)

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "12345"


@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_username_gets_no_bucket_and_is_a_validation_error(
    client, account, monkeypatch, value
):
    """`bool` is an `int` in Python, but not a username: no bucket, just a 400.

    With the account rate at 1/hour, a boolean that were given a bucket would
    be refused by the second attempt; each one is instead answered as the
    serializer answers it, and no key is written for any spelling a boolean
    could have been turned into.
    """
    monkeypatch.setitem(LoginAccountRateThrottle.THROTTLE_RATES, "auth_login_account", "1/hour")

    responses = [_login(client, username=value, password="wrong") for _ in range(3)]

    for response in responses:
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert "username" in error["details"]
    for spelling in (str(value), str(int(value)), str(value).lower()):
        assert cache.get(_account_bucket(spelling)) is None
    assert not ApiToken.objects.exists()
    # A real account is untouched by the boolean attempts.
    assert _login(client).status_code == 201


# --- what did not change ----------------------------------------------------------


def test_health_answers_whatever_token_is_sent(client):
    """A client with an expired token must not see the server as down."""
    response = client.get(reverse("v1:health"), HTTP_AUTHORIZATION="Bearer expired-or-garbage")

    assert response.status_code in (200, 503)
    assert "status" in response.json()


def test_the_authorization_header_passes_the_existing_cors_preflight(client, settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]

    response = client.options(
        reverse("v1:auth-me"),
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "authorization" in response["Access-Control-Allow-Headers"].lower()


def _png(png_bytes, name="label.png"):
    return SimpleUploadedFile(name, png_bytes, content_type="image/png")


def test_anonymous_demo_analysis_still_works_without_any_token(client, settings, png_bytes, media_root):
    settings.DEMO_PUBLIC_ANALYSIS_API = True

    rules = client.get(reverse("v1:rule-list"))
    conditions = client.get(reverse("v1:applicability-conditions"))
    extracted = client.post(reverse("v1:label-extract"), {"image": _png(png_bytes)})
    evaluated = client.post(
        reverse("v1:compliance-evaluate"),
        {"extraction_run_id": extracted.json()["id"]},
        content_type="application/json",
    )

    assert rules.status_code == conditions.status_code == 200
    assert extracted.status_code == 201
    assert evaluated.status_code == 201
    assert ExtractionRun.objects.get().image.uploaded_by is None
    assert ComplianceCheck.objects.get().requested_by is None


def test_with_the_demo_switch_off_anonymous_analysis_is_refused_as_before(client, settings, png_bytes):
    settings.DEMO_PUBLIC_ANALYSIS_API = False

    response = client.post(reverse("v1:label-extract"), {"image": _png(png_bytes)})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"


def test_a_rejected_token_on_a_demo_endpoint_is_not_served_as_anonymous(client, settings):
    """A client that thinks it is signed in is told otherwise, not downgraded."""
    settings.DEMO_PUBLIC_ANALYSIS_API = True

    _assert_token_rejected(client.get(reverse("v1:rule-list"), **_bearer("lmt_" + "C" * 43)))


def test_a_token_user_analyses_as_themselves_and_ownership_still_holds(
    client, account, other_account, settings, png_bytes, media_root
):
    """Existing authenticated behaviour, reached with a token instead of a session."""
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    mine = _bearer(_token_for(client))
    theirs = _bearer(_token_for(client, "other-inspector"))

    extracted = client.post(reverse("v1:label-extract"), {"image": _png(png_bytes)}, **mine)
    run_id = extracted.json()["id"]
    evaluated = client.post(
        reverse("v1:compliance-evaluate"), {"extraction_run_id": run_id},
        content_type="application/json", **mine,
    )
    stolen = client.post(
        reverse("v1:compliance-evaluate"), {"extraction_run_id": run_id},
        content_type="application/json", **theirs,
    )

    assert extracted.status_code == 201
    assert ExtractionRun.objects.get(pk=run_id).image.uploaded_by == account
    assert evaluated.status_code == 201
    assert ComplianceCheck.objects.get(pk=evaluated.json()["id"]).requested_by == account
    assert stolen.status_code == 400
    assert client.get(reverse("v1:compliance-evaluate"), **mine).json()["count"] == 1
    assert client.get(reverse("v1:compliance-evaluate"), **theirs).json()["count"] == 0


def test_the_admin_still_logs_in_with_a_session(client, db):
    get_user_model().objects.create_superuser("admin-user", "admin@example.test", PASSWORD)

    response = client.post(
        reverse("admin:login"),
        {"username": "admin-user", "password": PASSWORD, "next": "/admin/"},
    )

    assert response.status_code == 302
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/accounts/apitoken/").status_code == 200


def test_a_session_still_authenticates_the_api(client, account):
    client.force_login(account)

    assert _me(client).json()["username"] == "inspector"


def test_session_requests_still_need_csrf_and_token_requests_do_not(account, settings, png_bytes, media_root):
    settings.DEMO_PUBLIC_ANALYSIS_API = False
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(account)

    session_post = browser.post(reverse("v1:label-extract"), {"image": _png(png_bytes)})

    token_client = Client(enforce_csrf_checks=True)
    token = _token_for(token_client)
    token_post = token_client.post(
        reverse("v1:label-extract"), {"image": _png(png_bytes)}, **_bearer(token)
    )

    assert session_post.status_code == 403
    assert "CSRF" in session_post.json()["error"]["message"]
    assert token_post.status_code == 201
