"""Extraction API routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.
"""

from django.urls import path

from apps.extraction.api import views

urlpatterns = [
    path("", views.LabelExtractionView.as_view(), name="label-extract"),
]
