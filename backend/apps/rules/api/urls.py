"""Rule inventory routes.

Trailing slashes are required throughout the API - see `apps/core/api/urls.py`
for why.

One read-only route. There is deliberately no detail route and no write route:
a rule is identified by `code` in the list, and rules are changed by editing
`rules/definitions/` and running `manage.py load_rules`, not over the API.
"""

from django.urls import path

from apps.rules.api import views

urlpatterns = [
    path("", views.ComplianceRuleListView.as_view(), name="rule-list"),
]
