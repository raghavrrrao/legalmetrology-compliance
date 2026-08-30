"""Read a compliance result back.

The write path lives at `POST /api/v1/images/` (see `apps.images.api.views`),
which returns the whole result inline. This endpoint exists so a result can be
re-fetched by id - after a page reload, from a link, or by a reviewer who was
sent one - without re-uploading the photograph.
"""

from __future__ import annotations

from rest_framework import generics

from apps.compliance.api.permissions import IsAuthenticatedOrDemoPublic
from apps.compliance.api.serializers import ComplianceCheckSerializer
from apps.compliance.models import ComplianceCheck


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

        A result is rendered with its violations, each violation's evidence,
        and every declaration the run read. Left to the serializer that is a
        query per violation and per evidence row; prefetching makes it a fixed
        handful regardless of how many findings there are.
        """
        return (
            ComplianceCheck.objects.select_related(
                "extraction_run",
                "extraction_run__image",
                "product",
                "product__category",
            )
            .prefetch_related(
                "violations",
                "violations__evidence",
                "extraction_run__fields",
            )
            .all()
        )
