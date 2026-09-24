"""Request and response shapes for the authentication endpoints."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers


class LoginRequestSerializer(serializers.Serializer):
    """`POST /api/v1/auth/login/`.

    `username` because that is the account model's `USERNAME_FIELD`. Email is
    not unique on this model, so it cannot identify an account and is not
    accepted as a login name.

    `trim_whitespace=False` on the password: a password is compared exactly as
    typed, and a trailing space may be part of it.
    """

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(
        max_length=4096, trim_whitespace=False, style={"input_type": "password"}
    )


class UserSerializer(serializers.ModelSerializer):
    """The signed-in account, as a client needs it to say who is signed in.

    Deliberately short. No password hash, no permission or staff flags, no group
    membership and no login history: a client has no use for them, and a token
    that leaks should not also describe the account's privileges.
    """

    class Meta:
        model = get_user_model()
        fields = ["id", "username", "email", "first_name", "last_name"]
        read_only_fields = fields
