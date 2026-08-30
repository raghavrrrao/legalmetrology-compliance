"""Image API routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.
"""

from django.urls import path

from apps.images.api import views

urlpatterns = [
    path("", views.ImageAnalysisView.as_view(), name="image-analyse"),
]
