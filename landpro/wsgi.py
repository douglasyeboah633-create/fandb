"""
WSGI config for landpro project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'landpro.settings')

application = get_wsgi_application()

# --- Serverless cold-start: run migrations once per filesystem ----------------
# Vercel's function filesystem is read-only outside /tmp and rebuilt on every
# deploy, so there is no build step where `migrate` can run against the /tmp
# SQLite fallback. Without this, the first request hits missing tables
# (OperationalError) and Vercel reports 500 FUNCTION_INVOCATION_FAILED.
# Guarded by a marker file so a warm instance only migrates once.
if os.getenv("VERCEL", "").strip() == "1" and not os.getenv("DATABASE_URL", "").strip():
    _marker = "/tmp/landpro-migrated"
    if not os.path.exists(_marker):
        try:
            from django.core.management import call_command

            call_command("migrate", run_syncdb=True, interactive=False, verbosity=0)
            with open(_marker, "w") as _f:
                _f.write("ok")
        except Exception:
            pass
