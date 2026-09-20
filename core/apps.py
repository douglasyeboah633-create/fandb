from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "LandPro Records"

    def ready(self):
        # Register signal handlers (land status follows sales).
        from . import signals  # noqa: F401
