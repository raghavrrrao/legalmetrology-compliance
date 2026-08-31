"""Pagination shared by every list endpoint.

`core` is where a convention lives once more than one app has to agree on it -
the same reason `api/exceptions.py` and `api/permissions.py` are here. Nothing
in the API returned a collection until `GET /api/v1/compliance/` did, so there
was no pagination configuration to reuse and this file is the first statement
of one.

Page-number rather than cursor, deliberately. The screen this exists for is an
inspection history: a reviewer wants "the most recent results", occasionally
page two, and a count of how many results there are at all. `count` is the part
cursor pagination cannot give, and at the scale a single Legal Metrology
deployment holds the deep-offset cost that would justify a cursor is not the
cost being paid.

It is **not** registered as `DEFAULT_PAGINATION_CLASS` in settings. DRF's
default applies only to generic list views, of which there is exactly one, and
naming it on that view keeps its response shape a property of the endpoint
rather than of a global that a later branch could change from a distance. A
second list endpoint should name this same class.
"""

from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class DefaultPageNumberPagination(PageNumberPagination):
    """`?page=` and `?page_size=`, with the standard DRF envelope.

        {"count": 42, "next": "...?page=3", "previous": "...?page=1",
         "results": [...]}

    `page_size` is capped: an unbounded one would let a single anonymous
    request ask for every stored result at once, which is a denial-of-service
    lever rather than a convenience.

    An out-of-range or non-numeric `page` is a 404 through DRF's own
    `NotFound`, which the project's exception handler renders as the standard
    error envelope with code `not_found`. A malformed `page_size` falls back to
    the default rather than erroring - DRF's behaviour, left alone, because a
    client that mistypes a page size still wants its results.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
