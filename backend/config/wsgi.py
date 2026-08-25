"""WSGI entry point for synchronous deployment (gunicorn, uWSGI, mod_wsgi)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
