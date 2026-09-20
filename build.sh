#!/usr/bin/env bash
# Build script for Python hosts that run a build step (Render, Railway, Fly.io).
# Installs dependencies, collects static files and applies migrations.
set -o errexit

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Static files are served by WhiteNoise, so they must be collected at build time.
python manage.py collectstatic --noinput

# Apply database migrations on every deploy.
python manage.py migrate --noinput

# Optional: create the first administrator automatically.
# Set DJANGO_ADMIN_PASSWORD (and DJANGO_ADMIN_USERNAME) in the host's
# environment, then uncomment the next line.
# python manage.py create_admin
