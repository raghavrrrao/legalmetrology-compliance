"""Ask for a compliance verdict, read one back, and list the ones stored.

    POST /api/v1/compliance/          evaluate a stored reading
    GET  /api/v1/compliance/          list stored results, newest first
    GET  /api/v1/compliance/<uuid>/   read one result again

`POST /api/v1/images/` remains the one-shot path: upload a photograph and get
the verdict inline. The POST here is the other half of the two-step path that
`POST /api/v1/extraction/` opened - read the label first, look at what was
read, then ask what the rules make of it. Without it that endpoint is a dead
end, and getting a verdict for a reading you already have means uploading the
photograph a second time and evaluating a *different* reading of it.

The list is the history behind those two: the same stored checks, in the order
they were made, without the trace. It is a different *shape* of the same
records, not a different answer - see `ComplianceCheckListView`.

No view here decides anything. They call a service or read rows back and
serialize them; the verdict is `apps.compliance.services.engine`'s, drawn from
rule rows loaded from verified sources.
"""

from __future__ import annotations

import logging

from django.db.models import Count, IntegerField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductCategory
from apps.compliance.api.permissions import IsAuthenticatedOrDemoPublic
from apps.compliance.api.serializers import (
    ComplianceCheckListSerializer,
    ComplianceCheckSerializer,
    ComplianceEvaluationRequestSerializer,
)
from apps.compliance.models import (
    ComplianceCheck,
    ComplianceFinding,
    ComplianceViolation,
)
from apps.compliance.services import analysis_service
from apps.core.api.pagination import DefaultPageNumberPagination

logger = logging.getLogger(__name__)


class ComplianceEvaluationView(APIView):
    """`POST /api/v1/compliance/` - evaluate a stored reading against the rules.

    Takes the id of an `ExtractionRun` - what `POST /api/v1/extraction/`
    returns - and answers with the full `ComplianceCheck`: the verdict, the
    explanation, every rule that was examined and what it concluded, and the
    violations among them.

    **The photograph is not read again.** The verdict is drawn from the stored
    reading, so the declarations the caller was shown and the declarations the
    findings cite are the same ones. Re-running OCR could produce a different
    reading and therefore a finding about a value the user never saw.

    Returns **201**: a `ComplianceCheck` is a new record of an evaluation, not
    a lookup. Evaluating the same run twice is supported and creates two
    checks - that is how a result from before a rule was loaded stays
    comparable with one from after.

    **201 even when no conclusion could be drawn.** An unreadable reading, an
    unknown commodity category, or no loaded rules all produce a stored result
    whose verdict is `review_required` and whose summary explains which of
    those it was. That is the honest answer, not a failed request.

    **400** for an unknown `extraction_run_id` or an unknown `category_code`.

    A caller cannot choose which rules run. See
    `ComplianceEvaluationRequestSerializer` for why that matters.
    """

    permission_classes = [IsAuthenticatedOrDemoPublic]

    def post(self, request, *args, **kwargs) -> Response:
        request_data = ComplianceEvaluationRequestSerializer(data=request.data)
        request_data.is_valid(raise_exception=True)
        validated = request_data.validated_data

        # Already resolved to a row by the serializer, so the run this
        # evaluates is the one whose existence was validated.
        run = validated["extraction_run_id"]

        check = analysis_service.evaluate_run(
            run,
            category=self._category(validated.get("category_code")),
            requested_by=(
                request.user if request.user.is_authenticated else None
            ),
        )

        body = ComplianceCheckSerializer(
            check, context={"request": request}
        ).data
        return Response(body, status=status.HTTP_201_CREATED)

    @staticmethod
    def _category(code: str | None) -> ProductCategory | None:
        """Resolve a validated category code to its row.

        Existence was already checked in the serializer, so this cannot be the
        place a bad code is discovered. Returns None for an absent or empty
        code, which the engine treats as "the commodity is not known" -
        reported honestly in the result rather than guessed at.
        """
        if not code:
            return None
        return ProductCategory.objects.filter(code=code, is_active=True).first()


class ComplianceCheckDetailView(generics.RetrieveAPIView):
    """`GET /api/v1/compliance/<uuid>/` - one compliance result in full.

    The id is a UUID rather than a sequence number precisely so this endpoint
    can exist: a reviewer holding a link to their own result must not be able
    to walk to somebody else's by subtracting one.
    """

    serializer_class = ComplianceCheckSerializer
    permission_classes = [IsAuthenticatedOrDemoPublic]
    lookup_field = "pk"

    def get_queryset(self):
        """Load the whole result graph in a bounded number of queries.

        A result is rendered with its findings, its violations, each
        violation's evidence, and every declaration the run read. Left to the
        serializer that is a query per row; prefetching makes it a fixed
        handful regardless of how many rules were evaluated.
        """
        return (
            ComplianceCheck.objects.select_related(
                "extraction_run",
                "extraction_run__image",
                "product",
                "product__category",
            )
            .prefetch_related(
                "findings",
                "violations",
                "violations__evidence",
                "extraction_run__fields",
            )
            .all()
        )


def _related_row_count(queryset: QuerySet) -> Coalesce:
    """A per-check row count, as one correlated subquery on the outer query.

    Written as a subquery rather than `Count("findings", distinct=True)`
    because two counts over two multi-valued relations in one statement join
    both at once: a check with fifty findings and ten violations produces five
    hundred intermediate rows, per check, per page. `distinct=True` makes the
    numbers right and leaves the fan-out in place. Two correlated subqueries
    have no fan-out to correct.

    `Coalesce(..., 0)` because a check with no rows on the relation yields NULL
    from the subquery, and "no findings were recorded" is a zero, not an
    unknown. `order_by()` clears the related model's `Meta.ordering`, which
    would otherwise be dragged into the GROUP BY.
    """
    return Coalesce(
        Subquery(
            queryset.filter(compliance_check=OuterRef("pk"))
            .order_by()
            .values("compliance_check")
            .annotate(total=Count("pk"))
            .values("total")[:1],
            output_field=IntegerField(),
        ),
        0,
    )


class ComplianceCheckListView(generics.ListAPIView):
    """`GET /api/v1/compliance/` - stored results, newest first, paginated.

    The history behind the two endpoints above: what has been evaluated, when,
    and what came out. It is what an "Inspections" screen lists and navigates
    from; each row's `id` is the link to
    `GET /api/v1/compliance/<uuid>/`, which remains the only place the full
    trace lives.

    **Lightweight on purpose.** `ComplianceCheckListSerializer`, not
    `ComplianceCheckSerializer` - see that class for what is left out and why.
    Nothing here loads a finding, a violation, an evidence excerpt, a bounding
    box or the reading; the two counts are computed in the database.

    **Ordering is `-created_at, -id`, and the tie-breaker is not decoration.**
    `created_at` alone is not unique - a seeded demonstration, a test, or two
    evaluations of the same run inside one transaction can share a timestamp -
    and PostgreSQL is free to return equal-keyed rows in any order it likes.
    Under pagination that is worse than untidy: an unstable sort can show the
    same result on two pages and omit another entirely. `id` is a random UUID,
    so as a tie-break it is arbitrary but *fixed*, which is the property the
    pagination needs.

    **Query cost does not grow with the page.** One query for the count, one
    for the page - each carrying its two counting subqueries - plus the joins
    for the category, whatever the page size. See
    `apps/compliance/tests/test_history_api.py`, which asserts it.

    **No filtering, deliberately.** The repository has no filtering convention
    and no filter backend installed, and this endpoint does not invent one for
    a screen that does not exist yet. A `result` or date filter is a small,
    well-indexed addition when a client actually needs it - `check_result_idx`
    and the `created_at` index are already there - and adding it later is
    additive under the versioning rules in `docs/api.md`.

    **Permissions are the project's existing ones, and so is their limitation.**
    `IsAuthenticatedOrDemoPublic`, exactly as the other analysis endpoints. Any
    caller who is allowed through sees **every** stored check, not only their
    own: `requested_by` is recorded but not filtered on, because
    `ComplianceCheck` has no ownership model to filter by - a check requested
    anonymously has no owner at all. This is the same limitation the detail
    endpoint already has, in a more visible form. The detail endpoint requires
    guessing a UUID; this one lists them. It is documented in `docs/api.md`
    rather than half-fixed here: scoping history to `request.user` would leave
    anonymous demo checks unreachable by anybody and would still not stop a
    direct fetch by id, so ownership belongs to the authentication work, not to
    a list view.
    """

    serializer_class = ComplianceCheckListSerializer
    permission_classes = [IsAuthenticatedOrDemoPublic]
    pagination_class = DefaultPageNumberPagination

    def get_queryset(self) -> QuerySet[ComplianceCheck]:
        return (
            ComplianceCheck.objects.select_related("product", "product__category")
            .annotate(
                findings_count=_related_row_count(ComplianceFinding.objects),
                violations_count=_related_row_count(ComplianceViolation.objects),
            )
            .order_by("-created_at", "-id")
        )


class ComplianceCollectionView(ComplianceEvaluationView, ComplianceCheckListView):
    """The collection at `/api/v1/compliance/`: POST evaluates, GET lists.

    One URL can be routed to one view, so the two halves of the collection are
    composed here rather than each being routed separately. Both keep their own
    class, their own docstring and their own tests; this adds no behaviour of
    its own beyond joining them, and the POST is byte-for-byte the one that
    shipped.

    Order of bases matters: `ComplianceEvaluationView` first, so `post` comes
    from it and DRF's generic list machinery supplies only `get`.
    """
