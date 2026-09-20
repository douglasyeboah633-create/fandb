"""Template filters and tags used across LandPro templates."""

from django import template
from django.conf import settings

from ..utils import money as _money

register = template.Library()


@register.filter
def money(value):
    """Format a number with thousands separators, e.g. 12,500.00."""
    return _money(value)


@register.filter
def currency(value):
    """Format a number with the configured currency symbol."""
    return f"{settings.CURRENCY_SYMBOL} {_money(value)}"


@register.filter
def percent(value):
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "0%"


@register.filter
def status_badge(value):
    """Return a Bootstrap colour name for a land status."""
    return {
        "AVAILABLE": "success",
        "RESERVED": "warning",
        "SOLD": "secondary",
    }.get(str(value or "").upper(), "secondary")


@register.filter
def payment_badge(value):
    """Return a Bootstrap colour name for a payment status."""
    return {
        "FULLY_PAID": "success",
        "PARTIALLY_PAID": "warning",
        "NOT_PAID": "danger",
    }.get(str(value or "").upper(), "secondary")


@register.filter
def add_class(field, css):
    """Add a CSS class to a form field widget (used sparingly)."""
    existing = field.field.widget.attrs.get("class", "")
    field.field.widget.attrs["class"] = (existing + " " + css).strip()
    return field


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """Rebuild the current query string, overriding the given keys.

    Used to keep filters/search terms when paging through results.
    """
    request = context.get("request")
    if request is None:
        return ""
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()