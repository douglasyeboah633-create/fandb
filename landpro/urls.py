"""URL configuration for the LandPro Records Management System."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
]

# Uploaded documents are private. Serve them only through document_download,
# including in development; do not publish MEDIA_ROOT via a public web server.

# Friendly, non-technical error pages
handler400 = "core.views.error_400"
handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
