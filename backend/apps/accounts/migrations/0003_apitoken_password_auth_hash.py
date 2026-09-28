"""Record, on every API token, the password it was issued under.

Adds `ApiToken.password_auth_hash`: the user's `get_session_auth_hash()` at issue,
compared on every request so a password change ends the token. See the field's
help text and `apps/accounts/api/authentication.py`.

Three steps, so a database that already holds tokens from `0002_api_token` is
neither refused nor left with tokens that suddenly stop working:

1. add the column as nullable - a NOT NULL column with no default cannot be
   added to a table that already has rows;
2. fill it for every existing token with its user's *current* session-auth
   hash, so a token that worked before this migration still works after it
   (its user's password has not changed in between, by construction);
3. make it NOT NULL. If step 2 had missed a row, this fails loudly rather than
   leaving a token that no comparison could ever match.

Step 2 needs `get_session_auth_hash()`, which the historical `User` model in a
migration does not have - historical models carry fields, not methods. It calls
the method on an unsaved, in-memory instance of the real user model holding only
the stored password hash. That computes exactly what authentication will compute
with the same Django and the same SECRET_KEY, and it neither reads nor writes
through the real model, so it cannot be affected by later schema changes.
"""

from django.contrib.auth import get_user_model
from django.db import migrations, models

HELP_TEXT = (
    "The user's `get_session_auth_hash()` when the token was issued: an "
    "HMAC of their stored password hash, keyed with SECRET_KEY. The token "
    "authenticates only while it still matches, so changing the password "
    "stops every earlier token - the same check Django uses to end a "
    "user's sessions. Not the password, and not usable as one. 128 "
    "characters because Django's HMAC-SHA256 hex digest is 64 and a "
    "SHA-512 one would be 128."
)


def record_current_password_auth_hash(apps, schema_editor):
    """Give every existing token its user's current session-auth hash."""
    ApiToken = apps.get_model("accounts", "ApiToken")
    User = apps.get_model("accounts", "User")
    RealUser = get_user_model()
    db = schema_editor.connection.alias

    owners = User.objects.using(db).filter(
        api_tokens__password_auth_hash__isnull=True
    ).distinct()
    for owner in owners.iterator():
        auth_hash = RealUser(password=owner.password).get_session_auth_hash()
        ApiToken.objects.using(db).filter(
            user_id=owner.pk, password_auth_hash__isnull=True
        ).update(password_auth_hash=auth_hash)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_api_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="apitoken",
            name="password_auth_hash",
            field=models.CharField(
                editable=False, help_text=HELP_TEXT, max_length=128, null=True
            ),
        ),
        migrations.RunPython(
            record_current_password_auth_hash, migrations.RunPython.noop
        ),
        migrations.AlterField(
            model_name="apitoken",
            name="password_auth_hash",
            field=models.CharField(editable=False, help_text=HELP_TEXT, max_length=128),
        ),
    ]
