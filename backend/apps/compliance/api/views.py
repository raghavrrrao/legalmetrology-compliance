"""Ask for a compliance verdict, and read one back.

    POST /api/v1/compliance/          evaluate a stored reading
    GET  /api/v1/compliance/<uuid>/   read one result again

`POST /api/v1/images/` remains the one-shot path: upload a photograph and get
the verdict inline. The POST here is the other half of the two-step path that
`POST /api/v1/extraction/` opened - read the label first, look at what was
read, then ask what the rules make of it. Without it that endpoint is a dead
end, and getting a verdict for a reading you already have means uploading the
photograph a second time and evaluating a *different* reading of it.

Neither view decides anything. Both call a service and serialize what comes
back; the verdict is `apps.compliance.services.engine`'s, drawn from rule rows
loaded from verified sources.
"""

from __future__ import annotations

import logging

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductCategory
from apps.compliance.api.permissions import IsAuthenticatedOrDemoPublic
from apps.compliance.api.serializers import (
    ComplianceCheckSerializer,
    ComplianceEvaluationRequestSerializer,
)
from apps.compliance.models import ComplianceCheck
from apps.compliance.services import analysis_service

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
