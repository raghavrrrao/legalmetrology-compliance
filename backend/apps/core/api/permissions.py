"""Permission classes shared by more than one app.

`core` is where a convention lives once every app has to agree on it - the same
reason `api/exceptions.py` is here rather than in whichever app first needed an
error envelope. The class below started in `apps.compliance.api.permissions`,
where it was fine while compliance owned the only endpoints it guarded. It no
longer does: `apps.images` and `apps.extraction` guard theirs with it too, and
leaving it in compliance made both of them import *upward* into the app that
decides legal questions - the one dependency direction this project is careful
about. `apps.compliance.api.permissions` re-exports it, so nothing that already
imported it from there has to change.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission


class IsAuthenticatedOrDemoPublic(BasePermission):
    """Require a logged-in user unless the demo switch is deliberately on.

    The project's convention, stated in `docs/api.md` and enforced by
    `DEFAULT_PERMISSION_CLASSES`, is that every endpoint requires an
    authenticated user unless it explicitly opts out. Forgetting to think about
    permissions therefore fails closed.

    There is no login screen yet, and building one is not the work in front of
    us, so the demonstration needs the analysis endpoints reachable
    anonymously. That is a real relaxation, and it is written here rather than
    as a bare `AllowAny` on each view for three reasons:

    1. It is **off by default** (`DEMO_PUBLIC_ANALYSIS_API = False`), so a
       clone, a CI run and any deployment keep the deny-by-default behaviour.
       The permissive setting has to be turned on deliberately, in a local
       `.env` that is git-ignored - the same shape as the CORS decision in
       `config/settings.py`, where a permissive value is prevented from
       surviving into a deployment by accident.
    2. It is **one switch, named for what it is**. Grepping for the setting
       finds every endpoint it affects.
    3. It touches **only the analysis endpoints** - upload-and-analyse,
       upload-and-extract, and reading a stored result back. Nothing else in
       the API changes behaviour whether the flag is on or off.

    Anonymous does not mean unprotected: uploads still go through
    `apps.images.validators` in full, and DRF's anonymous throttle (30/min by
    default) still applies.

    The setting is read per request rather than captured when the class is
    defined. That is what makes the relaxation testable - a test can assert
    both the locked-down and the demo behaviour with `override_settings`
    instead of taking the default on trust - and it means flipping the flag
    needs a restart only because Django reloads settings then, not because
    this class cached anything.
    """

    message = (
        "This endpoint requires an authenticated user. Set "
        "DEMO_PUBLIC_ANALYSIS_API=True to open it for a local demonstration."
    )

    def has_permission(self, request, view) -> bool:
        if getattr(settings, "DEMO_PUBLIC_ANALYSIS_API", False):
            return True
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)
