"""Core API routes.

Trailing slashes are required throughout the API. Keep that consistent: a
client that omits one gets a redirect, which silently turns a POST into a GET.
"""

from django.urls import path

from apps.core.api import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
]
