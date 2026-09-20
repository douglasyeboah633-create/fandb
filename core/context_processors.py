"""Template context processors for branding information."""

from django.conf import settings

from .models import Setting, get_profile


def branding(request):
    """Expose business/branding settings to every template.

    Database values (editable from the Settings page) take precedence over
    the values in settings.py.
    """
    values = {row.key: row.value for row in Setting.objects.all()}

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