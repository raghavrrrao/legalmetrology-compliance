"""Authentication routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.
"""

from django.urls import path

from apps.accounts.api import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="auth-login"),
    path("logout/", views.LogoutView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="auth-me"),
]
