"""Who may reach the analysis endpoints.

The project's convention, stated in `docs/api.md` and enforced by
`DEFAULT_PERMISSION_CLASSES`, is that every endpoint requires an authenticated
user unless it explicitly opts out. Forgetting to think about permissions
therefore fails closed.

There is no login screen yet, and building one is not the work in front of us,
so the demonstration needs these two endpoints reachable anonymously. That is a
real relaxation and it is written here rather than as a bare `AllowAny` on each
view, for three reasons:

1. It is **off by default** (`DEMO_PUBLIC_ANALYSIS_API = False`), so a clone, a
   CI run and any deployment keep the deny-by-default behaviour. The permissive
   setting has to be turned on deliberately, in a local `.env` that is
   git-ignored - the same shape as the CORS decision in `config/settings.py`,
   where a permissive value is prevented from surviving into a deployment by
   accident.
2. It is **one switch, named for what it is**. Grepping for the setting finds
   every endpoint it affects.
3. It touches **only these endpoints**. Nothing else in the API changes
   behaviour whether the flag is on or off.

Anonymous does not mean unprotected: uploads still go through
`apps.images.validators` in full, and DRF's anonymous throttle (30/min by
default) still applies.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission


class IsAuthenticatedOrDemoPublic(BasePermission):
    """Require a logged-in user unless the demo switch is deliberately on.

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
