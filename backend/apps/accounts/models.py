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
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


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
