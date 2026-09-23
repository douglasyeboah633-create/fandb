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

# NOTE (Vercel): no auto-migrate here on purpose. Running `migrate` at import
# time on a cold start trips the serverless function timeout and Vercel
# reports it as 500 FUNCTION_INVOCATION_FAILED. The /tmp SQLite fallback is
# only for rendering pages before DATABASE_URL is set - real deployments must
# set DATABASE_URL (PostgreSQL) and run migrations against it, as DEPLOY.md
# explains. Missing tables then surface as a normal Django error page (with a
# clear "no such table" message) instead of a function crash.
