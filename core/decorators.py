"""Role based access control decorators."""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .models import get_profile


def _deny(request, message):
    messages.error(request, message)
    return redirect("core:dashboard")


def login_required_view(view_func):
    """Ensure the visitor is logged in before running the view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, "Please sign in to continue.")
            return redirect("core:login")
        return view_func(request, *args, **kwargs)

    return wrapper


def full_access_required(view_func):
    """Only administrators and managers may access the view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:login")
        profile = get_profile(request.user)
        if not profile or not profile.has_full_access:
            return _deny(
                request,
                "You do not have permission to access that page. "
                "Please contact your administrator.",
            )
        return view_func(request, *args, **kwargs)

    return wrapper


def admin_required(view_func):
    """Only administrators may access the view (user & settings management)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:login")
        profile = get_profile(request.user)
        if not profile or not profile.can_manage_users:
            return _deny(
                request,
                "Administrator access is required for that page.",
            )
        return view_func(request, *args, **kwargs)

    return wrapper


def delete_permission_required(view_func):
    """Staff need the delete permission granted by an administrator."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:login")
        profile = get_profile(request.user)
        if not profile or not profile.can_delete_records:
            return _deny(
                request,
                "You are not allowed to delete records. "
                "Ask an administrator to grant you delete permission.",
            )
        return view_func(request, *args, **kwargs)

    return wrapper
