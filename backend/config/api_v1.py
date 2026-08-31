"""URL routing for API version 1.

Each app owns its own `api_urls.py` and is included here under its own prefix.
That keeps feature branches out of each other's way: adding an endpoint means
editing your app's routing file, and this file changes only when a whole new
app appears.

Prefixes reserved for upcoming feature branches, left unrouted until the branch
that owns them lands. An empty router registered now would 404 in a way that
looks like a bug rather than like unfinished work:

    products/  feature/product-upload
    rules/     feature/rule-management

Three are routed. `images/` and `compliance/` are the demonstration flow,
upload through verdict. `extraction/` is the same upload stopping one stage
earlier, at what was read off the label - which is a different question and
deliberately a different endpoint, not a flag on that one. See docs/api.md.
"""

from django.urls import include, path, re_path

from apps.core.api.views import ApiNotFoundView

#: URL namespace for this version. Route names are "v1:<name>".
app_name = "v1"

urlpatterns = [
    path("", include("apps.core.api.urls")),
    path("images/", include("apps.images.api.urls")),
    path("extraction/", include("apps.extraction.api.urls")),
    path("compliance/", include("apps.compliance.api.urls")),
    # Must stay LAST: it claims every path the routes above did not, so that an
    # unmatched API URL returns the JSON error envelope rather than an HTML 404.
    re_path(r"^.*$", ApiNotFoundView.as_view(), name="not-found"),
]
