"""Abstract base models shared by every app.

These are abstract, so they create no tables of their own. They exist so that
timestamp and primary-key conventions are decided once rather than
inconsistently per feature branch.
"""

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds creation and last-modification timestamps.

    Both are stored in UTC (`USE_TZ = True`). `created_at` is set once and is
    the authoritative record of when a row first existed.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryKeyModel(models.Model):
    """Uses a random UUID as the primary key.

    Used for anything whose identifier appears in a URL or an API response.
    Sequential integer keys would leak how many objects the system holds and let
    one user enumerate another user's submissions by guessing neighbouring IDs,
    which matters here because these rows often represent user-submitted data.

    Internal tables that never surface an ID to a client keep the default
    BigAutoField - random UUID keys carry an index-locality cost that is not
    worth paying without a reason.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
