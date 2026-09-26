"""The project user model.

Why a custom user model exists on day one
-----------------------------------------
It is currently identical to Django's default. That is intentional. Swapping
`AUTH_USER_MODEL` after migrations have been applied is one of the few changes
in Django that genuinely requires tearing down and rebuilding the database, and
by then six people have local databases and several branches have foreign keys
pointing at the old table.

Adding it now costs one empty subclass. Adding it in three weeks costs the team
a coordinated database reset. This is the one piece of upfront structure in the
backend that is cheaper to do than to defer.

`feature/authentication` owns filling this in (roles, organisation, MFA) and
building the auth endpoints.

API tokens
----------
`ApiToken` is how the web and mobile clients authenticate: an opaque bearer
token sent in the `Authorization` header, because the production frontend is
hosted cross-site from the API and a session cookie cannot travel between them.
Only a hash of each token is stored; see `ApiToken` and `apps.accounts.tokens`.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class User(AbstractUser):
    """Project user.

    Inherits username, password, email, first/last name, the permission flags
    and `date_joined` from `AbstractUser`. No fields are added yet - add them
    when a feature actually needs them, with a migration.
    """

    class Meta(AbstractUser.Meta):
        db_table = "accounts_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.get_username()


class ApiToken(TimeStampedModel):
    """One API token issued to one user on one login.

    **The token itself is never stored.** `token_hash` is the SHA-256 of the
    token the client received, so a copy of this table - a backup, a leaked
    dump, an over-broad admin view - cannot be replayed against the API. The
    client sees the token once, in the login response, and nowhere else.

    A plain, unsalted SHA-256 is the right function here and is not a shortcut:
    the token is 256 bits from `secrets`, so there is nothing for a slow
    password hash to protect against, and a deterministic digest is what lets
    the token be found by an indexed lookup. Passwords are a different problem
    and stay with Django's password hashers.

    One row per login, so every device holds its own token. Logging out revokes
    the token the request used and no other; `revoked_at` records when, and a
    revoked token never authenticates again. Rows are kept after revocation or
    expiry rather than deleted, so an operator can see what was issued; purging
    them belongs with the retention work, not here.

    Changing the password ends every token issued before it, through
    `password_auth_hash` rather than `revoked_at`: the rows are not rewritten,
    they simply stop matching the user's new password hash and are refused.

    The primary key is the token's identifier - safe to show and to log, and
    the only thing that should ever be logged about a token.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        help_text="A token has no meaning without its user, so it goes with them.",
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        help_text="SHA-256 of the token, hex. The token itself is not stored.",
    )
    password_auth_hash = models.CharField(
        max_length=128,
        editable=False,
        help_text=(
            "The user's `get_session_auth_hash()` when the token was issued: an "
            "HMAC of their stored password hash, keyed with SECRET_KEY. The token "
            "authenticates only while it still matches, so changing the password "
            "stops every earlier token - the same check Django uses to end a "
            "user's sessions. Not the password, and not usable as one. 128 "
            "characters because Django's HMAC-SHA256 hex digest is 64 and a "
            "SHA-512 one would be 128."
        ),
    )
    expires_at = models.DateTimeField(
        db_index=True,
        help_text="Set at issue from API_TOKEN_LIFETIME_HOURS. Not extended by use.",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the token was revoked, by logout or by an operator. "
                  "Null while it has not been.",
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Approximate: refreshed at most every few minutes, so "
                  "authenticating does not write to the database on every request.",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "API token"
        verbose_name_plural = "API tokens"

    def __str__(self) -> str:
        return f"API token {self.pk} for {self.user}"

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now=None) -> bool:
        return self.expires_at <= (now or timezone.now())

    def is_usable(self, now=None) -> bool:
        """Whether this token may authenticate a request right now.

        The user's own `is_active` is checked by the authentication class too:
        deactivating an account stops every token it holds without touching
        them.
        """
        return not self.is_revoked and not self.is_expired(now)
