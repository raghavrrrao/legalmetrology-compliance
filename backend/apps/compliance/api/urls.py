"""Compliance API routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.
"""

from django.urls import path

from apps.compliance.api import views

urlpatterns = [
    path("", views.ComplianceEvaluationView.as_view(), name="compliance-evaluate"),
    path(
        "<uuid:pk>/",
        views.ComplianceCheckDetailView.as_view(),
        name="compliance-detail",
    ),
]
