"""`GET /api/v1/rules/` - the executable rules this installation has loaded.

An inventory, not a decision. It answers "which rules does this server hold, and
which of them does it evaluate?" - never "does this package comply?". That
question has one answer, the compliance engine's, reached per package from the
rules applicable to its commodity category and the facts stated about it. See
`apps.compliance.services.engine`.

Why it exists
-------------
A client that names the rules - the mobile Rules screen is the first - otherwise
has to carry its own copy of `rules/definitions/`, which says what the
repository ships and not what a given server loaded. A server that never ran
`load_rules`, or one where a rule was deactivated, would disagree with that copy
and nothing would say so. Serving the loaded rows is what makes the server the
source of truth for its own rule set.
"""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import generics

from apps.core.api.pagination import DefaultPageNumberPagination
from apps.core.api.permissions import IsAuthenticatedOrDemoPublic
from apps.rules.api.serializers import ComplianceRuleInventorySerializer
from apps.rules.models import ComplianceRule


class ComplianceRuleListView(generics.ListAPIView):
    """Every `ComplianceRule`, active and inactive, ordered by code, paginated.

    **Inactive rules are listed, with `is_active: false`.** A rule that is
    recorded but not evaluated - LM-PC-0002 as shipped - is the more important of
    the two facts for a reader to be able to find, and dropping it would make
    the inventory look more complete than the evaluation is. "Active" is the
    `is_active` flag and nothing more: whether an active rule actually runs for
    a package also depends on its effective window and the package's category,
    which the engine decides per check.

    **Read-only.** `ListAPIView` routes GET, HEAD and OPTIONS; anything else is a
    405 in the standard envelope. Rules are authored in `rules/definitions/`
    and loaded by `manage.py load_rules`, and editing them over the API is not
    something this endpoint offers.

    **Ordering is `code`, which is unique**, so the order is total and a page
    boundary can neither repeat nor drop a rule - the property
    `docs/api.md` requires of every paginated endpoint.

    **Permissions match `GET /api/v1/compliance/applicability-conditions/`**, the
    other endpoint that serves loaded legal-framework metadata:
    `IsAuthenticatedOrDemoPublic`. Nothing here is user data, and nothing here
    is scoped to a caller - every caller who may reach it sees the same rows.
    The permission is imported from `apps.core`, not from `apps.compliance`, so
    the rule catalogue does not depend on the app that evaluates it.

    Two queries whatever the page size: the count, and the page with its
    requirement joined in for `clause`.
    """

    serializer_class = ComplianceRuleInventorySerializer
    permission_classes = [IsAuthenticatedOrDemoPublic]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self) -> QuerySet[ComplianceRule]:
        return ComplianceRule.objects.select_related("rule_requirement").order_by(
            "code"
        )
