"""URL routing for API version 1.

Each app owns its own `api_urls.py` and is included here under its own prefix.
That keeps feature branches out of each other's way: adding an endpoint means
editing your app's routing file, and this file changes only when a whole new
app appears.

Prefixes reserved for upcoming feature branches, left unrouted until the branch
that owns them lands. An empty router registered now would 404 in a way that
looks like a bug rather than like unfinished work:

    products/    feature/product-upload
    extraction/  feature/ocr-processing
    rules/       feature/rule-management

`images/` and `compliance/` are now routed: together they are the whole
demonstration flow, upload through verdict. See docs/api.md.
"""

from django.urls import include, path, re_path

from apps.core.api.views import ApiNotFoundView

#: URL namespace for this version. Route names are "v1:<name>".
app_name = "v1"

urlpatterns = [
    path("", include("apps.core.api.urls")),
    path("images/", include("apps.images.api.urls")),
    path("compliance/", include("apps.compliance.api.urls")),
    # Must stay LAST: it claims every path the routes above did not, so that an
    # unmatched API URL returns the JSON error envelope rather than an HTML 404.
    re_path(r"^.*$", ApiNotFoundView.as_view(), name="not-found"),
]
