"""Compliance API routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.

The collection route serves two methods - POST evaluates a stored reading, GET
lists the results already stored - through `ComplianceCollectionView`, which
composes the two views that implement them. Its name is still
`compliance-evaluate`: the POST was routed first and existing callers and tests
reverse it, and renaming a route for tidiness would break them for nothing.
"""

from django.urls import path

from apps.compliance.api import views

urlpatterns = [
    path("", views.ComplianceCollectionView.as_view(), name="compliance-evaluate"),
    path(
        "<uuid:pk>/",
        views.ComplianceCheckDetailView.as_view(),
        name="compliance-detail",
    ),
]
