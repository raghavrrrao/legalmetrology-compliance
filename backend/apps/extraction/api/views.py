"""`POST /api/v1/extraction/` - read a label, and stop there.

Reserved in `docs/api.md` since the base structure landed and unrouted until
now. It is the HTTP face of the stage the architecture puts between validation
and the rule engine:

    image -> validate -> OCR -> field extraction -> normalisation -> [here]
                                                 -> rule engine -> findings

`POST /api/v1/images/` runs that whole line and answers with a verdict. This
endpoint answers with the reading alone. Both matter, and the difference is not
cosmetic:

- A reading is an observation about a photograph. A verdict is a claim about a
  package under the Legal Metrology (Packaged Commodities) Rules, 2011. Only
  the rule engine may make the second, and only from verified rules.
- Evaluating the extractor - which is how `docs/evaluation-results.md` gets its
  numbers - means looking at what was read, with no rule in the way.
- A caller that has not identified the commodity cannot get a meaningful
  verdict anyway, and should not be pushed into creating a `Product` row to ask
  what is written on a photograph.

So this view takes no `category_code`, creates no `Product`, and never touches
`apps.compliance`. The response has no `compliance` key and must not grow one.

Like the analysis endpoint it is synchronous: extraction measures at a ~2.2 s
median on the configured Tesseract pipeline (docs/evaluation-results.md), which
is inside the frontend client's timeout, so there is nothing to poll. When
`run_extraction` moves behind a queue this response gains a `pending` shape
additively, as `docs/api.md` describes.

This view calls one service and serializes what comes back. It re-implements no
validation, writes no rows itself, and opens no transaction - the last of those
matters, because `run_extraction` manages its own so that a failed extraction
still leaves a `failed` run behind explaining why.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import IsAuthenticatedOrDemoPublic
from apps.extraction.api.serializers import ExtractionResponseSerializer
from apps.extraction.services import extraction_service
from apps.images.api.serializers import ImageUploadSerializer

logger = logging.getLogger(__name__)


class LabelExtractionView(APIView):
    """Upload a label photograph and receive what was read off it.

    Returns **201** with the `ExtractionRun`, its declarations, and the stored
    image.

    A 201 even when nothing could be read. An unreadable photograph still
    produces a real, stored, retrievable run whose `status` is `empty` or
    `failed`, whose `error_code` says which, and whose
    `produced_usable_output` is `false`. That is an outcome the caller needs,
    not a failed request - and reporting it as a 4xx would tell the client its
    *request* was wrong when the request was fine.

    The 4xx cases are genuinely bad requests: no file, an unknown `view_type`,
    or a file the validators reject.

    A 500 is reserved for the one case that is a bug rather than an outcome: an
    engine that ran and then broke its own output contract. The failed run is
    recorded first by the service, so the image does not sit in `processing`
    forever, and the exception is then re-raised rather than filed away as "the
    photograph was unreadable". The client sees the standard generic 500; the
    traceback is logged server-side and never returned.
    """

    permission_classes = [IsAuthenticatedOrDemoPublic]
    # MultiPart for the browser's form upload; FormParser so a body with no
    # file at all still parses and fails as a validation error naming the
    # missing field, rather than as an unsupported media type.
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs) -> Response:
        request_data = ImageUploadSerializer(data=request.data)
        request_data.is_valid(raise_exception=True)
        validated = request_data.validated_data

        try:
            outcome = extraction_service.ingest_and_extract(
                validated["image"],
                uploaded_by=(
                    request.user if request.user.is_authenticated else None
                ),
                view_type=validated["view_type"],
            )
        except DjangoValidationError as exc:
            # The upload was rejected by apps.images.validators - too large,
            # not a decodable image, a format we do not accept. Nothing was
            # stored and no run exists.
            #
            # Re-raised as a DRF ValidationError keyed to the request field so
            # the standard envelope stays structured (details.image=[...]).
            # `exc.messages` carries the reason; the validator's `code` does
            # not survive the shared exception handler today, which docs/api.md
            # records as an open question about error handling rather than
            # something this endpoint should solve locally.
            logger.info("Upload rejected: %s", exc.messages)
            raise drf_exceptions.ValidationError({"image": exc.messages}) from exc

        body = ExtractionResponseSerializer(
            outcome.run, context={"request": request}
        ).data
        return Response(body, status=status.HTTP_201_CREATED)
