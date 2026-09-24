"""Compliance API routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.

The collection route serves two methods - POST evaluates a stored reading, GET
lists the results already stored - through `ComplianceCollectionView`, which
composes the two views that implement them. Its name is still
`compliance-evaluate`: the POST was routed first and existing callers and tests
reverse it, and renaming a route for tidiness would break them for nothing.

`applicability-conditions/` is the discovery half of the POST's contract: the
facts a submitter may state that would change what the engine concludes. It
sits here rather than under the `rules/` prefix because what it lists is the
input vocabulary of the endpoint beside it rather than the rule set itself.
`rules/` was reserved for `feature/rule-management` when this was written, and
now serves that branch's rule inventory, `GET /api/v1/rules/`.
"""

from django.urls import path

from apps.compliance.api import applicability_views, views

urlpatterns = [
    path("", views.ComplianceCollectionView.as_view(), name="compliance-evaluate"),
    # Before the UUID route, and it has to stay there. `<uuid:pk>` will not
    # match this path, so the order is not load-bearing today - but a future
    # `<str:pk>` would swallow it silently, and a literal path above a
    # converter is the arrangement that cannot break that way.
    path(
        "applicability-conditions/",
        applicability_views.ApplicabilityConditionListView.as_view(),
        name="applicability-conditions",
    ),
    path(
        "<uuid:pk>/",
        views.ComplianceCheckDetailView.as_view(),
        name="compliance-detail",
    ),
]
