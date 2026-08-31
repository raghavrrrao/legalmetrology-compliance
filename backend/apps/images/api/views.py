"""`POST /api/v1/images/` - the one endpoint the demonstration flow needs.

Upload a photograph; get back the whole result: what was read off the label,
which rules applied, what was found, and the verdict with its explanation.

For the reading on its own - no rules, no verdict, no `Product` row - see
`POST /api/v1/extraction/` in `apps.extraction.api.views`. Both run the same
extraction service over the same validated upload; this one carries on into the
rule engine afterwards.

Synchronous, and that is a decision rather than an oversight. `docs/api.md`
left "synchronous or queued" open; extraction against the configured Tesseract
pipeline measures at a 2.2 s median (docs/evaluation-results.md), which is
inside the frontend client's 15 s timeout, and returning the finished result
means the UI needs no polling and no "pending" state to render. When extraction
becomes slow enough to need a queue, `run_extraction` is the function that
moves behind it - as its own docstring says - and this view's response gains a
`pending` shape then, additively.

This view calls one service and serializes what comes back. It re-implements no
validation, writes no rows itself, and opens no transaction - see
`apps.compliance.services.analysis_service` for why the last of those matters.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ProductCategory
from apps.compliance.api.serializers import ComplianceCheckSerializer
from apps.compliance.services import analysis_service
from apps.core.api.permissions import IsAuthenticatedOrDemoPublic
from apps.images.api.serializers import ImageAnalysisRequestSerializer

logger = logging.getLogger(__name__)


class ImageAnalysisView(APIView):
    """Upload a label photograph and receive its compliance result.

    Returns **201** with the complete `ComplianceCheck`.

    A 201 even when nothing could be read: an unreadable photograph still
    creates a real, stored, retrievable result whose verdict is
    REVIEW_REQUIRED and whose summary explains that the image could not be
    read. That is an outcome, not a failure, and reporting it as a 4xx would
    tell the client its *request* was wrong when the request was fine.

    The 4xx cases are genuinely bad requests: no file, an unknown category, or
    a file the validators reject.
    """

    permission_classes = [IsAuthenticatedOrDemoPublic]
    # MultiPart for the browser's form upload; FormParser so a body with no
    # file at all still parses and fails as a validation error naming the
    # missing field, rather than as an unsupported media type.
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs) -> Response:
        request_data = ImageAnalysisRequestSerializer(data=request.data)
        request_data.is_valid(raise_exception=True)
        validated = request_data.validated_data

        category = self._category(validated.get("category_code"))

        try:
            outcome = analysis_service.analyse_upload(
                validated["image"],
                category=category,
                uploaded_by=(
                    request.user if request.user.is_authenticated else None
                ),
                view_type=validated["view_type"],
            )
        except DjangoValidationError as exc:
            # The upload was rejected by apps.images.validators.
            # Raise as a DRF ValidationError keyed to the request field so the
            # standard error envelope stays structured (details.image=[...]).
            logger.info("Upload rejected: %s", exc.messages)
            from rest_framework import exceptions as drf_exceptions

            raise drf_exceptions.ValidationError({"image": exc.messages}) from exc

        body = ComplianceCheckSerializer(
            outcome.check, context={"request": request}
        ).data
        return Response(body, status=status.HTTP_201_CREATED)

    @staticmethod
    def _category(code: str | None) -> ProductCategory | None:
        """Resolve a validated category code to its row.

        Existence was already checked in the serializer, so this cannot be the
        place a bad code is discovered. Returns None for an absent or empty
        code, which the analysis service treats as "the commodity is not
        known" - reported honestly in the result rather than guessed at.
        """
        if not code:
            return None
        try:
            return ProductCategory.objects.get(code=code, is_active=True)
        except ProductCategory.DoesNotExist as exc:
            from rest_framework import exceptions as drf_exceptions

            raise drf_exceptions.ValidationError(
                {
                    "category_code": [
                        f"No active product category with code {code!r}. Load categories with `manage.py seed_categories`."
                    ]
                }
            ) from exc
