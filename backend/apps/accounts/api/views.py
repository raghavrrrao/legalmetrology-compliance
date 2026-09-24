"""Sign in, sign out, and who am I - the API authentication endpoints.

    POST /api/v1/auth/login/    credentials -> a new Bearer token (shown once)
    POST /api/v1/auth/logout/   revoke the token this request used
    GET  /api/v1/auth/me/       the account the request is authenticated as

There is no sign-up, password reset or e-mail verification: accounts are created
by an administrator, and those flows are later work. Nothing here changes who
may use the analysis endpoints - a token only identifies the caller, and
`IsAuthenticatedOrDemoPublic` still decides as before.
"""

from __future__ import annotations

from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.authentication import BearerTokenAuthentication
from apps.accounts.api.serializers import LoginRequestSerializer, UserSerializer
from apps.accounts.api.throttles import LoginAccountRateThrottle, LoginClientRateThrottle
from apps.accounts.models import ApiToken
from apps.accounts.tokens import issue_token, revoke_token

#: One message for every rejected login. A wrong password, an unknown username
#: and an inactive account are indistinguishable from outside, so the response
#: cannot be used to find out which usernames exist.
LOGIN_FAILED_MESSAGE = "Unable to sign in with the credentials provided."


class LoginView(APIView):
    """`POST /api/v1/auth/login/` - exchange a username and password for a token.

    **201** with a new token, because each login creates one: a second device,
    or the same device after logging out, gets its own, and revoking one leaves
    the others working.

    **401** `authentication_failed` for any rejected credentials. Django's
    `ModelBackend` checks the password and refuses inactive accounts, and it
    runs the password hasher even for a username that does not exist, so the
    response takes about as long either way.

    **429** `rate_limited` past either login throttle - see `throttles.py`.

    No authentication classes: signing in needs no credentials, and a stale or
    malformed token left in a client's header must not stop it signing in again.
    That also means no session, and so no CSRF check - there is no cookie here
    for a cross-site form to ride on, and the token comes back in a body that
    CORS keeps from any page not on the allowed list.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginClientRateThrottle, LoginAccountRateThrottle]

    def post(self, request, *args, **kwargs) -> Response:
        credentials = LoginRequestSerializer(data=request.data)
        credentials.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=credentials.validated_data["username"],
            password=credentials.validated_data["password"],
        )
        if user is None or not user.is_active:
            raise exceptions.AuthenticationFailed(LOGIN_FAILED_MESSAGE)

        token, raw = issue_token(user)
        update_last_login(None, user)
        return Response(
            {
                "token": raw,
                "token_type": "Bearer",
                "expires_at": token.expires_at,
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def get_authenticate_header(self, request):
        """A 401 must carry a challenge; name the scheme the client should use."""
        return 'Bearer realm="api"'


class LogoutView(APIView):
    """`POST /api/v1/auth/logout/` - revoke the Bearer token this request used.

    Only that token. The same account signed in on another device keeps
    working, because each device holds its own token.

    Bearer authentication only: a session has no token to revoke, so a request
    authenticated by a session cookie is answered as unauthenticated rather than
    told it logged out when nothing changed.

    **204** on success. Repeating the call with the same token is a **401**,
    because a revoked token must never authenticate anything again - including a
    second logout. The token stays revoked either way, so the effect of calling
    this twice is the effect of calling it once.
    """

    authentication_classes = [BearerTokenAuthentication]

    def post(self, request, *args, **kwargs) -> Response:
        if isinstance(request.auth, ApiToken):
            revoke_token(request.auth)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """`GET /api/v1/auth/me/` - the account this request is authenticated as.

    Authenticated by a Bearer token or, for the admin's own browser, a session.
    The permission is the API default, `IsAuthenticated`, so an anonymous
    request is refused - with demo mode on or off, since there is no account to
    describe.
    """

    def get(self, request, *args, **kwargs) -> Response:
        return Response(UserSerializer(request.user).data)
