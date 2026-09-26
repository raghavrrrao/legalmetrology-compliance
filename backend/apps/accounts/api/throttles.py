"""Rate limits on `POST /api/v1/auth/login/` - the brute-force guard.

Two throttles, both DRF `SimpleRateThrottle`s on the same cache and settings as
the API's existing anonymous and user throttles, and both applied to every login
attempt:

`auth_login`          per client address (`API_THROTTLE_LOGIN`)
`auth_login_account`  per username tried (`API_THROTTLE_LOGIN_ACCOUNT`)

The second is the one that bounds password guessing, and the reason there are
two. The client address comes from DRF's `get_ident`, which - with `NUM_PROXIES`
unset, as it is - reads `X-Forwarded-For` as the client sent it through the
proxy, so a client that varies that header lands in a new bucket each time. The
per-account limit keys on the account being attacked instead, which no header
changes. Its cost is the usual one: somebody who knows a username can use up
that account's allowance and delay its owner's login until the window passes.

Both count successful logins too. A token lasts for days, so a person logs in
rarely, and a throttle that counted only failures would need its own bookkeeping
outside DRF's.

The counters live in the default cache, which is per-process `LocMemCache`
(`config/settings.py`). With one gunicorn worker - the deployment default - the
limits are exact; with N workers they are roughly N times looser. That is the
same limitation every throttle in this API has, and the same fix: a shared
cache before raising `WEB_CONCURRENCY`.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


class LoginClientRateThrottle(SimpleRateThrottle):
    """Login attempts per client address."""

    scope = "auth_login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginAccountRateThrottle(SimpleRateThrottle):
    """Login attempts per username, whatever address they come from.

    The username is folded to lower case, so varying its case does not buy a
    new allowance, and hashed, so the cache key is fixed-length and carries no
    username. A body without a usable username is not throttled here; it fails
    validation without reaching the password check.

    A JSON number is a usable username. `LoginRequestSerializer`'s `CharField`
    accepts an int or a float and signs in with `str()` of it, so `12345` and
    `"12345"` are the same account and must be the same bucket - otherwise
    sending the number would sidestep this limit entirely. A boolean is not:
    `bool` is a subclass of `int`, but the `CharField` rejects it, so it can
    never reach the password check and gets no bucket.
    """

    scope = "auth_login_account"

    def get_cache_key(self, request, view):
        data = request.data
        username = data.get("username") if hasattr(data, "get") else None
        if isinstance(username, bool):
            return None
        if isinstance(username, (int, float)):
            username = str(username)
        if not isinstance(username, str) or not username.strip():
            return None
        digest = hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
