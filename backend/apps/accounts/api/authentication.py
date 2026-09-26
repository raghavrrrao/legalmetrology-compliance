"""`Authorization: Bearer <token>` - how the web and mobile clients authenticate.

Listed first in `DEFAULT_AUTHENTICATION_CLASSES`, ahead of
`SessionAuthentication`, which stays for the Django admin and for any
same-origin session use. The order decides two things:

- **A Bearer token wins.** A request that carries one is authenticated by it,
  and session authentication - with its CSRF check - is never consulted. CSRF
  protects credentials a browser attaches on its own; a header the client
  script chose to send is not one.
- **A request without one is treated exactly as before.** `authenticate`
  returns None when there is no `Bearer` credential, so an anonymous demo
  request and a session request reach the next class unchanged, and the
  permission classes decide as they always have.

Failure is deliberately uniform. A token that is malformed, unknown, revoked,
expired, belongs to an inactive user, or was issued before the user's password
last changed all raise the same `AuthenticationFailed` with the same message, so
a response never says which - and never repeats the token back. A request that
*presented* a Bearer token and had it rejected is not quietly served as
anonymous: a client that believes it is signed in must be told otherwise, not
have its work stored without an owner.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from apps.accounts.models import ApiToken
from apps.accounts.tokens import hash_token, is_well_formed

#: Case-insensitive, as RFC 7235 makes the scheme name.
KEYWORD = "bearer"

#: The one message every token failure produces. It names no reason.
INVALID_TOKEN_MESSAGE = "Invalid or expired token."

#: `last_used_at` is refreshed at most this often, so authentication is not a
#: database write on every request.
LAST_USED_RESOLUTION = timedelta(minutes=5)


def _presents_bearer(request) -> bool:
    parts = get_authorization_header(request).split()
    return bool(parts) and parts[0].lower() == KEYWORD.encode()


def _password_unchanged_since_issue(token: ApiToken) -> bool:
    """Whether the user's password is the one the token was issued under.

    The comparison Django makes before trusting a session: the token's recorded
    `get_session_auth_hash()` against the user's current one, in constant time.
    Setting a new password - even back to the old one, since each hash has a
    fresh salt - changes the current value, and every earlier token stops here.

    Like Django's sessions, a hash made with a key in `SECRET_KEY_FALLBACKS` is
    also accepted, so rotating `SECRET_KEY` the documented way does not sign
    every client out; the token is moved onto the current key as it is used.
    With no fallbacks configured - as today - that branch finds nothing.
    """
    user = token.user
    current = user.get_session_auth_hash()
    if constant_time_compare(token.password_auth_hash, current):
        return True
    if any(
        constant_time_compare(token.password_auth_hash, fallback)
        for fallback in user.get_session_auth_fallback_hash()
    ):
        ApiToken.objects.filter(pk=token.pk).update(password_auth_hash=current)
        token.password_auth_hash = current
        return True
    return False


class BearerTokenAuthentication(BaseAuthentication):
    """Authenticate a request by the `ApiToken` its Bearer header names."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != KEYWORD.encode():
            # No Authorization header, or another scheme: not ours to judge.
            return None
        if len(parts) != 2:
            # "Bearer" alone, or with spaces inside the token.
            raise exceptions.AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        try:
            raw = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed(INVALID_TOKEN_MESSAGE) from None
        if not is_well_formed(raw):
            raise exceptions.AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        return self._authenticate_token(raw)

    @staticmethod
    def _authenticate_token(raw: str):
        now = timezone.now()
        token = (
            ApiToken.objects.select_related("user")
            .filter(token_hash=hash_token(raw))
            .first()
        )
        if (
            token is None
            or not token.is_usable(now)
            or not token.user.is_active
            or not _password_unchanged_since_issue(token)
        ):
            raise exceptions.AuthenticationFailed(INVALID_TOKEN_MESSAGE)

        if token.last_used_at is None or now - token.last_used_at >= LAST_USED_RESOLUTION:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
            token.last_used_at = now

        # `request.auth` is the token row, so logout can revoke exactly the
        # token this request used and no other.
        return token.user, token

    def authenticate_header(self, request):
        """The `WWW-Authenticate` challenge - only for requests that used Bearer.

        DRF answers an authentication failure with 401 when the first
        authentication class returns a challenge here, and 403 when it returns
        None. So a rejected Bearer token gets the 401 a token client expects,
        while a request that sent no credentials still gets the 403
        `not_authenticated` every existing client already handles - adding
        token authentication changes nothing for the web or mobile builds that
        do not send one.
        """
        if _presents_bearer(request):
            return 'Bearer realm="api", error="invalid_token"'
        return None
