"""Root URL configuration.

Everything the frontend talks to lives under a version prefix:

    /api/v1/...

Adding `/api/v2/` later is a new include here; v1 clients keep working. Within
a version, new endpoints are additive and existing response shapes do not
change - see docs/api.md for the compatibility rules.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # The version is both the URL prefix and the namespace, so route names
    # read as "v1:health" and a future v2 gets its own namespace rather
    # than colliding with v1 names.
    path("api/v1/", include("config.api_v1")),
]

if settings.DEBUG:
    # Django only serves uploaded files in development. In a deployed
    # environment this is handled by the web server or object storage, with
    # access control - uploaded product images are not public.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
