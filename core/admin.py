"""Django admin registrations (a secondary, power-user interface)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    AuditLog,
    Customer,
    Document,
    Land,
    Payment,
    Sale,
    Setting,
    UserProfile,
)


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "first_name", "last_name", "email", "is_active")


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("customer_id", "full_name", "phone", "ghana_card", "date_registered")
    search_fields = ("customer_id", "full_name", "phone", "ghana_card", "email")
    list_filter = ("date_registered",)
    ordering = ("-created_at",)


@admin.register(Land)
class LandAdmin(admin.ModelAdmin):
    list_display = ("land_id", "plot_number", "block_number", "location",
                    "land_type", "price", "status", "date_added")
    list_filter = ("status", "land_type", "region")
    search_fields = ("land_id", "plot_number", "block_number", "location",
                     "community", "district")
    ordering = ("plot_number",)


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("transaction_id", "customer", "land", "selling_price",
                    "sale_date", "sales_agent")
    search_fields = ("transaction_id", "customer__full_name",
                     "land__plot_number", "land__land_id")
    list_filter = ("sale_date", "payment_method")
    ordering = ("-sale_date",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("payment_id", "receipt_number", "sale", "amount",
                    "payment_date", "payment_method", "recorded_by")
    search_fields = ("payment_id", "receipt_number", "sale__transaction_id",
                     "sale__customer__full_name")
    list_filter = ("payment_method", "payment_date")
    ordering = ("-payment_date",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "document_type", "customer", "land", "sale",
                    "uploaded_by", "uploaded_at")
    list_filter = ("document_type",)
    search_fields = ("title", "description")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "model_name",
                    "object_repr", "ip_address")
    list_filter = ("action", "model_name")
    search_fields = ("object_repr", "description", "user__username")
    ordering = ("-created_at",)
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key", "value")
