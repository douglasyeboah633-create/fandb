"""Template context processors for branding information."""

from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import Setting, get_profile


def branding(request):
    """Expose business/branding settings to every template.

    Database values (editable from the Settings page) take precedence over
    the values in settings.py.

    On a fresh serverless deploy the database may not be migrated yet, so a
    missing ``core_setting`` table must not crash every page (Vercel reports
    that as ``500 FUNCTION_INVOCATION_FAILED``). Fall back to settings.py
    values until migrations have run.
    """
    try:
        values = {row.key: row.value for row in Setting.objects.all()}
    except (OperationalError, ProgrammingError):
        values = {}

    def pick(key, fallback):
        value = values.get(key)
        return value if value else fallback

    return {
        "BUSINESS_NAME": pick("business_name", settings.BUSINESS_NAME),
        "BUSINESS_SHORT_NAME": settings.BUSINESS_SHORT_NAME,
        "BUSINESS_TAGLINE": settings.BUSINESS_TAGLINE,
        "BUSINESS_PHONE": pick("business_phone", settings.BUSINESS_PHONE),
        "BUSINESS_EMAIL": pick("business_email", settings.BUSINESS_EMAIL),
        "BUSINESS_ADDRESS": pick("business_address", settings.BUSINESS_ADDRESS),
        "CURRENCY_SYMBOL": pick("currency_symbol", settings.CURRENCY_SYMBOL),
        "user_profile": get_profile(getattr(request, "user", None)),
    }