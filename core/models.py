"""Database models for the ABI LAND Records Management System.

Tables: users (Django auth) + user profiles, customers, lands, sales,
payments, documents, audit logs, application settings and the flat
land-records table used by the main Records screen.

All monetary values use DecimalField to avoid floating point rounding errors.
"""

import re
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_code(queryset, field_name: str, prefix: str, width: int = 4) -> str:
    """Generate the next sequential, human friendly code for a record.

    Example: ``next_code(Customer.objects.all(), "customer_id", "CUS-")``
    returns ``CUS-0007`` when ``CUS-0006`` is the highest existing code.
    """
    highest = 0
    for value in queryset.values_list(field_name, flat=True):
        match = re.search(r"(\d+)\s*$", str(value or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:0{width}d}"


# ---------------------------------------------------------------------------
# User roles
# ---------------------------------------------------------------------------
class UserProfile(models.Model):
    """Extra information and role based permissions for a system user."""

    ROLE_ADMIN = "ADMIN"
    ROLE_MANAGER = "MANAGER"
    ROLE_STAFF = "STAFF"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_STAFF, "Staff / Worker"),
    ]

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)
    phone = models.CharField(max_length=30, blank=True)
    can_delete = models.BooleanField(
        default=False, help_text="Allow this staff member to delete records."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User profile"
        verbose_name_plural = "User profiles"

    def __str__(self) -> str:
        name = self.user.get_full_name() or self.user.username
        return f"{name} ({self.get_role_display()})"

    # -- Role helpers -------------------------------------------------------
    @property
    def is_administrator(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role == self.ROLE_MANAGER

    @property
    def has_full_access(self) -> bool:
        """Administrators and managers can access every record."""
        return self.role in {self.ROLE_ADMIN, self.ROLE_MANAGER}

    @property
    def can_delete_records(self) -> bool:
        """Full access users can delete; staff only when explicitly allowed."""
        return self.has_full_access or self.can_delete

    @property
    def can_manage_users(self) -> bool:
        return self.is_administrator

    @property
    def can_manage_settings(self) -> bool:
        return self.is_administrator

    @property
    def role_label(self) -> str:
        return self.get_role_display()


def get_profile(user):
    """Return the profile for a user, or None for anonymous users.

    On a fresh serverless deploy the database may not be migrated yet, so a
    missing ``core_userprofile`` table must not crash every page (Vercel
    reports that as ``500 FUNCTION_INVOCATION_FAILED``).
    """
    from django.db import OperationalError, ProgrammingError

    if not user or not user.is_authenticated:
        return None
    try:
        profile, _ = UserProfile.objects.get_or_create(user=user)
    except (OperationalError, ProgrammingError):
        return None
    return profile


# ---------------------------------------------------------------------------
# Customers / buyers
# ---------------------------------------------------------------------------
class Customer(models.Model):
    customer_id = models.CharField(
        "Customer ID", max_length=30, unique=True, blank=True
    )
    full_name = models.CharField("Full name", max_length=150)
    ghana_card = models.CharField(
        "Ghana Card / ID number", max_length=60, unique=True, blank=True, null=True
    )
    phone = models.CharField("Phone number", max_length=30)
    alt_phone = models.CharField("Alternative phone", max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField("Residential address", max_length=255, blank=True)
    occupation = models.CharField(max_length=120, blank=True)
    date_registered = models.DateField(default=timezone.localdate)
    next_of_kin = models.CharField(max_length=150, blank=True)
    next_of_kin_phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="customers_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.customer_id})"

    def save(self, *args, **kwargs):
        if not self.customer_id:
            self.customer_id = next_code(
                Customer.objects.all(), "customer_id", "CUS-"
            )
        super().save(*args, **kwargs)

    @property
    def sales_count(self) -> int:
        return self.sales.count()

    @property
    def total_purchases(self) -> Decimal:
        return self.sales.aggregate(total=Sum("selling_price"))["total"] or Decimal("0.00")

    @property
    def total_paid(self) -> Decimal:
        total = Payment.objects.filter(sale__customer=self).aggregate(
            total=Sum("amount")
        )["total"]
        return total or Decimal("0.00")

    @property
    def outstanding_balance(self) -> Decimal:
        return self.total_purchases - self.total_paid

    @property
    def is_owing(self) -> bool:
        return self.outstanding_balance > Decimal("0.00")

    def get_absolute_url(self):
        return reverse("core:customer_detail", args=[self.pk])


# ---------------------------------------------------------------------------
# Land / property records
# ---------------------------------------------------------------------------
class Land(models.Model):
    STATUS_AVAILABLE = "AVAILABLE"
    STATUS_RESERVED = "RESERVED"
    STATUS_SOLD = "SOLD"
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_RESERVED, "Reserved"),
        (STATUS_SOLD, "Sold"),
    ]

    TYPE_RESIDENTIAL = "RESIDENTIAL"
    TYPE_COMMERCIAL = "COMMERCIAL"
    TYPE_INDUSTRIAL = "INDUSTRIAL"
    TYPE_AGRICULTURAL = "AGRICULTURAL"
    TYPE_MIXED = "MIXED"
    TYPE_OTHER = "OTHER"
    TYPE_CHOICES = [
        (TYPE_RESIDENTIAL, "Residential"),
        (TYPE_COMMERCIAL, "Commercial"),
        (TYPE_INDUSTRIAL, "Industrial"),
        (TYPE_AGRICULTURAL, "Agricultural"),
        (TYPE_MIXED, "Mixed Use"),
        (TYPE_OTHER, "Other"),
    ]

    SIZE_UNIT_CHOICES = [
        ("ACRES", "Acres"),
        ("HECTARES", "Hectares"),
        ("PLOT", "Plot(s)"),
        ("SQM", "Square metres"),
    ]

    land_id = models.CharField("Land ID", max_length=30, unique=True, blank=True)
    plot_number = models.CharField("Plot number", max_length=50)
    block_number = models.CharField("Block number", max_length=50, blank=True)
    location = models.CharField(max_length=150)
    region = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    community = models.CharField(max_length=120, blank=True)
    land_size = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    size_unit = models.CharField(
        "Unit", max_length=20, choices=SIZE_UNIT_CHOICES, default="PLOT"
    )
    land_type = models.CharField(
        "Land type", max_length=20, choices=TYPE_CHOICES, default=TYPE_RESIDENTIAL
    )
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE
    )
    date_added = models.DateField(default=timezone.localdate)
    description = models.TextField(blank=True)
    gps_coordinates = models.CharField(
        "GPS / location information", max_length=120, blank=True
    )
    assigned_staff = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lands_assigned",
    )
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lands_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["plot_number", "block_number"],
                name="unique_plot_per_block",
            )
        ]

    def __str__(self) -> str:
        return f"{self.land_id} - Plot {self.plot_number} ({self.location})"

    def save(self, *args, **kwargs):
        self.block_number = (self.block_number or "").strip()
        if not self.land_id:
            self.land_id = next_code(Land.objects.all(), "land_id", "LND-")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.price is not None and self.price < 0:
            raise ValidationError({"price": "Price cannot be negative."})
        if self.land_size is not None and self.land_size < 0:
            raise ValidationError({"land_size": "Land size cannot be negative."})

    @property
    def status_badge(self) -> str:
        return {
            self.STATUS_AVAILABLE: "success",
            self.STATUS_RESERVED: "warning",
            self.STATUS_SOLD: "secondary",
        }.get(self.status, "secondary")

    @property
    def is_available(self) -> bool:
        return self.status == self.STATUS_AVAILABLE

    @property
    def active_sale(self):
        return getattr(self, "sale", None)

    def get_absolute_url(self):
        return reverse("core:land_detail", args=[self.pk])


# ---------------------------------------------------------------------------
# Sales / transactions
# ---------------------------------------------------------------------------
class Sale(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ("CASH", "Cash"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("BANK_TRANSFER", "Bank Transfer"),
        ("CHEQUE", "Cheque"),
        ("OTHER", "Other"),
    ]

    STATUS_FULLY_PAID = "FULLY_PAID"
    STATUS_PARTIAL = "PARTIALLY_PAID"
    STATUS_UNPAID = "NOT_PAID"

    transaction_id = models.CharField(
        "Transaction ID", max_length=30, unique=True, blank=True
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="sales"
    )
    land = models.OneToOneField(Land, on_delete=models.PROTECT, related_name="sale")
    selling_price = models.DecimalField(max_digits=14, decimal_places=2)
    sale_date = models.DateField(default=timezone.localdate)
    sales_agent = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_made",
    )
    payment_method = models.CharField(
        "Initial payment method", max_length=20,
        choices=PAYMENT_METHOD_CHOICES, default="CASH",
    )
    notes = models.TextField("Transaction notes", blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sales_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.transaction_id} - {self.customer.full_name}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = next_code(
                Sale.objects.all(), "transaction_id", "TXN-"
            )
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.selling_price is not None and self.selling_price <= 0:
            raise ValidationError(
                {"selling_price": "Selling price must be greater than zero."}
            )

    # -- Derived payment figures (always calculated, never stored) ----------
    @property
    def total_paid(self) -> Decimal:
        total = self.payments.aggregate(total=Sum("amount"))["total"]
        return total or Decimal("0.00")

    @property
    def outstanding_balance(self) -> Decimal:
        balance = self.selling_price - self.total_paid
        return balance if balance > Decimal("0.00") else Decimal("0.00")

    @property
    def payment_status(self) -> str:
        paid = self.total_paid
        if paid <= Decimal("0.00"):
            return self.STATUS_UNPAID
        if paid >= self.selling_price:
            return self.STATUS_FULLY_PAID
        return self.STATUS_PARTIAL

    @property
    def payment_status_display(self) -> str:
        return {
            self.STATUS_UNPAID: "Not Paid",
            self.STATUS_PARTIAL: "Partially Paid",
            self.STATUS_FULLY_PAID: "Fully Paid",
        }.get(self.payment_status, "Not Paid")

    @property
    def payment_status_badge(self) -> str:
        return {
            self.STATUS_UNPAID: "danger",
            self.STATUS_PARTIAL: "warning",
            self.STATUS_FULLY_PAID: "success",
        }.get(self.payment_status, "secondary")

    @property
    def progress_percent(self) -> int:
        if not self.selling_price:
            return 0
        percent = (self.total_paid / self.selling_price) * 100
        return int(min(max(percent, 0), 100))

    @property
    def is_fully_paid(self) -> bool:
        return self.payment_status == self.STATUS_FULLY_PAID

    def get_absolute_url(self):
        return reverse("core:sale_detail", args=[self.pk])


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class Payment(models.Model):
    payment_id = models.CharField(
        "Payment ID", max_length=30, unique=True, blank=True
    )
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate)
    payment_method = models.CharField(
        "Payment method", max_length=20,
        choices=Sale.PAYMENT_METHOD_CHOICES, default="CASH",
    )
    receipt_number = models.CharField(
        "Receipt number", max_length=30, unique=True, blank=True
    )
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments_recorded",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.payment_id} - {self.receipt_number} ({self.amount})"

    def save(self, *args, **kwargs):
        if not self.payment_id:
            self.payment_id = next_code(
                Payment.objects.all(), "payment_id", "PAY-", width=5
            )
        if not self.receipt_number:
            self.receipt_number = next_code(
                Payment.objects.all(), "receipt_number", "RCT-", width=5
            )
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= 0:
            raise ValidationError(
                {"amount": "Payment amount must be greater than zero."}
            )

    @property
    def customer(self):
        return self.sale.customer

    @property
    def land(self):
        return self.sale.land

    @property
    def method_display(self) -> str:
        return self.get_payment_method_display()

    def get_absolute_url(self):
        return reverse("core:payment_detail", args=[self.pk])


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class Document(models.Model):
    TYPE_LAND = "LAND"
    TYPE_AGREEMENT = "AGREEMENT"
    TYPE_RECEIPT = "RECEIPT"
    TYPE_SITE_PLAN = "SITE_PLAN"
    TYPE_ID = "IDENTIFICATION"
    TYPE_ALLOCATION = "ALLOCATION"
    TYPE_OTHER = "OTHER"
    TYPE_CHOICES = [
        (TYPE_LAND, "Land document"),
        (TYPE_AGREEMENT, "Agreement"),
        (TYPE_RECEIPT, "Receipt"),
        (TYPE_SITE_PLAN, "Site plan"),
        (TYPE_ID, "Identification document"),
        (TYPE_ALLOCATION, "Allocation document"),
        (TYPE_OTHER, "Other supporting document"),
    ]

    title = models.CharField(max_length=150)
    document_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_OTHER
    )
    file = models.FileField(upload_to="documents/%Y/%m/")
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True,
        related_name="documents",
    )
    land = models.ForeignKey(
        Land, on_delete=models.CASCADE, null=True, blank=True,
        related_name="documents",
    )
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, null=True, blank=True,
        related_name="documents",
    )
    description = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="documents_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if not (self.customer or self.land or self.sale):
            raise ValidationError(
                "Link this document to at least one record "
                "(customer, land or sale)."
            )

    @property
    def linked_to(self) -> str:
        parts = []
        if self.customer:
            parts.append(f"Customer: {self.customer.full_name}")
        if self.land:
            parts.append(f"Land: {self.land.land_id} / Plot {self.land.plot_number}")
        if self.sale:
            parts.append(f"Sale: {self.sale.transaction_id}")
        return " | ".join(parts) or "-"

    @property
    def extension(self) -> str:
        name = self.file.name if self.file else ""
        return name.rsplit(".", 1)[-1].upper() if "." in name else ""


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    ACTION_CREATE = "CREATE"
    ACTION_UPDATE = "UPDATE"
    ACTION_DELETE = "DELETE"
    ACTION_LOGIN = "LOGIN"
    ACTION_LOGOUT = "LOGOUT"
    ACTION_EXPORT = "EXPORT"
    ACTION_BACKUP = "BACKUP"
    ACTION_CHOICES = [
        (ACTION_CREATE, "Created"),
        (ACTION_UPDATE, "Updated"),
        (ACTION_DELETE, "Deleted"),
        (ACTION_LOGIN, "Logged in"),
        (ACTION_LOGOUT, "Logged out"),
        (ACTION_EXPORT, "Exported data"),
        (ACTION_BACKUP, "Backed up data"),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    model_name = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Activity log"
        verbose_name_plural = "Activity logs"

    def __str__(self) -> str:
        who = self.user.username if self.user else "System"
        return f"{who} {self.get_action_display()} {self.object_repr}".strip()

    @property
    def action_badge(self) -> str:
        return {
            self.ACTION_CREATE: "success",
            self.ACTION_UPDATE: "info",
            self.ACTION_DELETE: "danger",
            self.ACTION_LOGIN: "primary",
            self.ACTION_LOGOUT: "secondary",
            self.ACTION_EXPORT: "warning",
            self.ACTION_BACKUP: "dark",
        }.get(self.action, "secondary")

    @classmethod
    def log(cls, user, action, obj=None, description="", ip_address=None):
        """Create an audit trail entry for an important action."""
        if obj is not None:
            model_name = obj.__class__.__name__
            object_id = str(getattr(obj, "pk", "") or "")
            object_repr = str(obj)[:200]
        else:
            model_name, object_id, object_repr = "", "", ""
        return cls.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None,
            action=action,
            model_name=model_name,
            object_id=object_id,
            object_repr=object_repr,
            description=description,
            ip_address=ip_address,
        )


# ---------------------------------------------------------------------------
# Application settings (editable by administrators)
# ---------------------------------------------------------------------------
class Setting(models.Model):
    key = models.CharField(max_length=60, unique=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key

    DEFAULTS = {
        "business_name": "ABI LAND",
        "business_phone": "+233 00 000 0000",
        "business_email": "info@landpro.example",
        "business_address": "Accra, Ghana",
        "currency_symbol": "GHS",
        "allow_overpayment": "False",
    }

    @classmethod
    def get(cls, key, default=None):
        if default is None:
            default = cls.DEFAULTS.get(key, "")
        row = cls.objects.filter(key=key).first()
        return row.value if row and row.value != "" else default

    @classmethod
    def get_bool(cls, key, default=False):
        value = str(cls.get(key, str(default))).strip().lower()
        return value in {"1", "true", "yes", "on"}

    @classmethod
    def set(cls, key, value):
        obj, _ = cls.objects.get_or_create(key=key)
        obj.value = str(value)
        obj.save(update_fields=["value", "updated_at"])
        return obj


# ---------------------------------------------------------------------------
# Land records - the single flat record table
# ---------------------------------------------------------------------------
class LandRecord(models.Model):
    """One line of the record table.

    A complete, self-contained land sale record (buyer, plot, money, receipt)
    so records can be kept in one table without filling other forms first.
    """

    UNIT_CHOICES = [
        ("ACRES", "Acres"),
        ("PLOTS", "Plots"),
        ("HECTARES", "Hectares"),
        ("SQUARE_METRES", "Square metres"),
        ("FEET", "Feet"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("CASH", "Cash"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("BANK_TRANSFER", "Bank transfer"),
        ("CHEQUE", "Cheque"),
        ("OTHER", "Other"),
    ]
    STATUS_PAID = "PAID"
    STATUS_PART = "PART"
    STATUS_UNPAID = "UNPAID"

    record_number = models.CharField(
        "Record no.", max_length=30, unique=True, blank=True
    )
    record_date = models.DateField("Date", default=timezone.localdate)
    buyer_name = models.CharField("Buyer / customer", max_length=150)
    phone = models.CharField("Phone", max_length=30, blank=True)
    id_number = models.CharField("Ghana card / ID", max_length=60, blank=True)
    plot_number = models.CharField("Plot no.", max_length=60, blank=True)
    location = models.CharField("Location / community", max_length=150, blank=True)
    land_size = models.DecimalField(
        "Size", max_digits=10, decimal_places=2, null=True, blank=True
    )
    size_unit = models.CharField(
        "Unit", max_length=20, choices=UNIT_CHOICES, default="ACRES"
    )
    total_price = models.DecimalField(
        "Total price", max_digits=14, decimal_places=2, null=True, blank=True
    )
    amount_paid = models.DecimalField(
        "Amount paid", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    payment_method = models.CharField(
        "Method of receipt", max_length=20,
        choices=PAYMENT_METHOD_CHOICES, default="CASH",
    )
    receipt_number = models.CharField(
        "Receipt no.", max_length=30, unique=True, blank=True
    )
    notes = models.TextField("Notes / details", blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="land_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-record_date", "-created_at"]
        verbose_name = "land record"
        verbose_name_plural = "land records"

    def __str__(self) -> str:
        return f"{self.record_number} - {self.buyer_name}"

    def save(self, *args, **kwargs):
        if not self.record_number:
            self.record_number = next_code(
                LandRecord.objects.all(), "record_number", "REC-", width=5
            )
        if not self.receipt_number:
            self.receipt_number = next_code(
                LandRecord.objects.all(), "receipt_number", "RCT-", width=5
            )
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        paid = self.amount_paid or Decimal("0.00")
        if self.amount_paid is not None and self.amount_paid < 0:
            raise ValidationError(
                {"amount_paid": "The amount paid cannot be negative."}
            )
        if self.total_price is not None and self.total_price < 0:
            raise ValidationError(
                {"total_price": "The total price cannot be negative."}
            )
        if self.total_price is not None and paid > self.total_price:
            raise ValidationError(
                {"amount_paid": "The amount paid cannot be more than the "
                                "total price."}
            )
        if self.land_size is not None and self.land_size < 0:
            raise ValidationError({"land_size": "The size cannot be negative."})

    # -- Derived values (calculated, never stored) -------------------------
    @property
    def balance(self):
        """Money still owed, or None when no total price was recorded."""
        if self.total_price is None:
            return None
        balance = self.total_price - (self.amount_paid or Decimal("0.00"))
        return balance if balance > Decimal("0.00") else Decimal("0.00")

    @property
    def payment_status(self) -> str:
        if self.total_price is None:
            return ""
        paid = self.amount_paid or Decimal("0.00")
        if paid <= Decimal("0.00"):
            return self.STATUS_UNPAID
        if paid >= self.total_price:
            return self.STATUS_PAID
        return self.STATUS_PART

    @property
    def payment_status_display(self) -> str:
        return {
            self.STATUS_PAID: "Fully paid",
            self.STATUS_PART: "Part paid",
            self.STATUS_UNPAID: "Not paid",
        }.get(self.payment_status, "—")

    @property
    def payment_status_badge(self) -> str:
        return {
            self.STATUS_PAID: "success",
            self.STATUS_PART: "warning",
            self.STATUS_UNPAID: "danger",
        }.get(self.payment_status, "secondary")

    @property
    def size_display(self) -> str:
        if self.land_size is None:
            return "—"
        return f"{self.land_size.normalize():f} {self.get_size_unit_display()}"

    def get_absolute_url(self):
        return reverse("core:record_receipt", args=[self.pk])
