"""
ASGI config for landpro project.

The project runs on WSGI in production (see landpro/wsgi.py), but this
standard ASGI module is kept so Django tooling that probes for it (checks,
Vercel's manage.py entrypoint discovery) does not crash at import time.
Deployment entry remains WSGI_APPLICATION = "landpro.wsgi.application".
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'landpro.settings')

application = get_asgi_application()

