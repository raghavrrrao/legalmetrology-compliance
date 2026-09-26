"""Issuing, recognising and revoking API tokens.

The only module that creates a token or turns one into a hash, so the format and
the digest are decided in one place.

Format
------
    lmt_<43 characters of URL-safe base64>

`secrets.token_urlsafe(32)`: 256 bits from the operating system's CSPRNG. The
`lmt_` prefix ("legal metrology token") carries no secret; it makes a leaked
token recognisable - to a secret scanner, to someone reading a log - and lets the
authentication class reject anything that is not one of ours before touching
the database. A string that does not match the format exactly is never hashed
or looked up.

Nothing in this module logs a token, puts one in an exception message, or
returns one except `issue_token`, whose caller hands it to the client once.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import ApiToken

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "lmt_"
#: 32 random bytes in URL-safe base64 without padding is exactly 43 characters.
_TOKEN_RE = re.compile(r"^lmt_[A-Za-z0-9_-]{43}$")


def is_well_formed(raw: str) -> bool:
    """Whether `raw` has the shape of a token this project issues."""
    return bool(_TOKEN_RE.fullmatch(raw))


def hash_token(raw: str) -> str:
    """The stored form of a token: SHA-256, hex. See `ApiToken` for why SHA-256."""
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def token_lifetime() -> timedelta:
    """How long a newly issued token is valid, from `API_TOKEN_LIFETIME_HOURS`."""
    return timedelta(hours=settings.API_TOKEN_LIFETIME_HOURS)


def issue_token(user) -> tuple[ApiToken, str]:
    """Create a token for `user`; return the stored row and the raw token.

    The raw token is the only copy that will ever exist. The caller returns it
    to the client and keeps nothing.

    `password_auth_hash` records the user's password as it stands now - as
    Django's session-auth HMAC, never the password - so the token stops
    authenticating once the password changes. Call this after authentication:
    `authenticate()` may rehash the stored password (an upgraded hasher), and the
    token must record the hash the user now has.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken.objects.create(
        user=user,
        token_hash=hash_token(raw),
        password_auth_hash=user.get_session_auth_hash(),
        expires_at=timezone.now() + token_lifetime(),
    )
    logger.info("Issued API token %s for user %s", token.pk, user.pk)
    return token, raw


def revoke_token(token: ApiToken) -> None:
    """Revoke `token` if it is not already revoked. Other tokens are untouched.

    A conditional UPDATE rather than a read-then-save, so two concurrent logouts
    record one revocation time and neither overwrites the other.
    """
    now = timezone.now()
    revoked = ApiToken.objects.filter(pk=token.pk, revoked_at__isnull=True).update(
        revoked_at=now, updated_at=now
    )
    if revoked:
        token.revoked_at = now
        logger.info("Revoked API token %s for user %s", token.pk, token.user_id)
