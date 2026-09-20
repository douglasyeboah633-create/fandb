"""URL routes for the LandPro Records Management System."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # Authentication & dashboard
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),

    # Records table (the main working screen)
    path("records/", views.records, name="records"),
    path("records/<int:pk>/receipt/", views.record_receipt, name="record_receipt"),

    # Customers / buyers
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/add/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_update, name="customer_update"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="customer_delete"),

    # Land records
    path("lands/", views.land_list, name="land_list"),
    path("lands/add/", views.land_create, name="land_create"),
    path("lands/<int:pk>/", views.land_detail, name="land_detail"),
    path("lands/<int:pk>/edit/", views.land_update, name="land_update"),
    path("lands/<int:pk>/status/<str:status>/", views.land_set_status,
         name="land_set_status"),
    path("lands/<int:pk>/delete/", views.land_delete, name="land_delete"),

    # Sales / transactions
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/add/", views.sale_create, name="sale_create"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/edit/", views.sale_update, name="sale_update"),
    path("sales/<int:pk>/delete/", views.sale_delete, name="sale_delete"),

    # Payments
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/register/", views.payment_register, name="payment_register"),
    path("payments/add/", views.payment_create, name="payment_create"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("payments/<int:pk>/edit/", views.payment_update, name="payment_update"),
    path("payments/<int:pk>/delete/", views.payment_delete, name="payment_delete"),

    # Receipts
    path("receipts/", views.receipt_list, name="receipt_list"),
    path("receipts/<int:pk>/print/", views.receipt_print, name="receipt_print"),
    path("receipts/<int:pk>/pdf/", views.receipt_pdf, name="receipt_pdf"),

    # Documents
    path("documents/", views.document_list, name="document_list"),
    path("documents/upload/", views.document_create, name="document_create"),
    path("documents/<int:pk>/download/", views.document_download, name="document_download"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),

    # Search
    path("search/", views.global_search, name="search"),

    # Reports
    path("reports/", views.reports_index, name="reports_index"),
    path("reports/<slug:kind>/", views.report_view, name="report_view"),

    # Activity / audit log
    path("activity/", views.audit_log_list, name="audit_list"),

    # Users (administrator only)
    path("users/", views.user_list, name="user_list"),
    path("users/add/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_update, name="user_update"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),

    # Settings & backup (administrator only)
    path("settings/", views.settings_view, name="settings"),
    path("settings/backup/", views.backup_view, name="backup"),
]