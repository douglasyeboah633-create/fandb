"""Forms for the ABI LAND Records Management System.

All forms validate their input and render with Bootstrap 5 classes.
"""

import re
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    Customer,
    Document,
    Land,
    LandRecord,
    Payment,
    Sale,
    Setting,
    UserProfile,
)
from .utils import currency

PHONE_RE = re.compile(r"^[0-9+\-()\s]{7,20}$")


def validate_phone(value: str):
    """Validate a phone number (Ghana and international formats)."""
    value = (value or "").strip()
    if not value:
        raise forms.ValidationError("Phone number is required.")
    digits = re.sub(r"\D", "", value)
    if not PHONE_RE.match(value) or len(digits) < 7 or len(digits) > 15:
        raise forms.ValidationError(
            "Enter a valid phone number, e.g. 0244123456 or +233244123456."
        )
    return value


class BootstrapFormMixin:
    """Add Bootstrap 5 classes and placeholders to every form widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = (existing + " form-check-input").strip()
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs["class"] = (existing + " form-select").strip()
            elif isinstance(widget, forms.DateInput):
                widget.attrs["class"] = (existing + " form-control").strip()
                widget.input_type = "date"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = (existing + " form-control").strip()
                widget.attrs.setdefault("rows", 3)
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs["class"] = (existing + " form-control").strip()
            else:
                widget.attrs["class"] = (existing + " form-control").strip()

            if field.required:
                widget.attrs.setdefault("required", "required")


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Login form with friendly error messages."""

    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "Username"}),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"placeholder": "Password"}),
    )

    error_messages = {
        "invalid_login": "Incorrect username or password. Please try again.",
        "inactive": "This account has been disabled. Contact the administrator.",
    }


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "full_name", "ghana_card", "phone", "alt_phone", "email",
            "address", "occupation", "date_registered", "next_of_kin",
            "next_of_kin_phone", "notes",
        ]
        widgets = {
            "date_registered": forms.DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_full_name(self):
        name = (self.cleaned_data.get("full_name") or "").strip()
        if len(name) < 3:
            raise forms.ValidationError("Enter the customer's full name.")
        return name

    def clean_phone(self):
        return validate_phone(self.cleaned_data.get("phone"))

    def clean_alt_phone(self):
        value = (self.cleaned_data.get("alt_phone") or "").strip()
        if value:
            return validate_phone(value)
        return value

    def clean_next_of_kin_phone(self):
        value = (self.cleaned_data.get("next_of_kin_phone") or "").strip()
        if value:
            return validate_phone(value)
        return value

    def clean_ghana_card(self):
        value = (self.cleaned_data.get("ghana_card") or "").strip().upper()
        if value:
            duplicates = Customer.objects.filter(ghana_card__iexact=value)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise forms.ValidationError(
                    "A customer with this Ghana Card / ID number already exists."
                )
        return value

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()


# ---------------------------------------------------------------------------
# Land records
# ---------------------------------------------------------------------------
class LandForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Land
        fields = [
            "plot_number", "block_number", "location", "region", "district",
            "community", "land_size", "size_unit", "land_type", "price",
            "status", "date_added", "gps_coordinates", "assigned_staff",
            "description", "notes",
        ]
        widgets = {
            "date_added": forms.DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_staff"].queryset = User.objects.filter(
            is_active=True
        ).order_by("first_name", "username")
        self.fields["assigned_staff"].label_from_instance = (
            lambda user: user.get_full_name() or user.username
        )
        self.fields["assigned_staff"].required = False

    def clean_plot_number(self):
        value = (self.cleaned_data.get("plot_number") or "").strip()
        if not value:
            raise forms.ValidationError("Plot number is required.")
        return value

    def clean_block_number(self):
        return (self.cleaned_data.get("block_number") or "").strip()

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is None or price <= 0:
            raise forms.ValidationError("Enter a valid price greater than zero.")
        return price

    def clean(self):
        cleaned = super().clean()
        plot = cleaned.get("plot_number")
        block = (cleaned.get("block_number") or "").strip()
        if plot:
            duplicates = Land.objects.filter(
                plot_number__iexact=plot, block_number__iexact=block
            )
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                label = f"Plot {plot}" + (f", Block {block}" if block else "")
                raise forms.ValidationError(
                    f"{label} already exists. Plot numbers must be unique."
                )
        return cleaned


# ---------------------------------------------------------------------------
# Sales / transactions
# ---------------------------------------------------------------------------
class SaleForm(BootstrapFormMixin, forms.ModelForm):
    initial_payment = forms.DecimalField(
        label="Initial amount paid", required=False, min_value=Decimal("0"),
        max_digits=14, decimal_places=2, initial=Decimal("0.00"),
        help_text="Optional. Creates the first payment and receipt immediately.",
    )
    initial_payment_method = forms.ChoiceField(
        label="Initial payment method", required=False,
        choices=Sale.PAYMENT_METHOD_CHOICES, initial="CASH",
    )

    class Meta:
        model = Sale
        fields = ["customer", "land", "selling_price", "sale_date",
                  "sales_agent", "payment_method", "notes"]
        widgets = {
            "sale_date": forms.DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q

        available = Land.objects.filter(sale__isnull=True)
        if self.instance.pk:
            available = Land.objects.filter(
                Q(sale__isnull=True) | Q(pk=self.instance.land_id)
            )
        self.fields["land"].queryset = available.order_by("plot_number")
        self.fields["land"].label_from_instance = (
            lambda land: f"{land.land_id} - Plot {land.plot_number}, {land.location}"
        )
        self.fields["customer"].queryset = Customer.objects.order_by("full_name")
        self.fields["customer"].label_from_instance = (
            lambda c: f"{c.full_name} ({c.customer_id})"
        )
        self.fields["sales_agent"].queryset = User.objects.filter(
            is_active=True
        ).order_by("first_name", "username")
        self.fields["sales_agent"].label_from_instance = (
            lambda user: user.get_full_name() or user.username
        )
        self.fields["sales_agent"].required = False
        self.fields["sale_date"].initial = timezone.localdate()
        if self.instance.pk:
            # Initial payment only applies when creating a sale.
            self.fields.pop("initial_payment", None)
            self.fields.pop("initial_payment_method", None)

    def clean_selling_price(self):
        price = self.cleaned_data.get("selling_price")
        if price is None or price <= 0:
            raise forms.ValidationError("Enter a selling price greater than zero.")
        return price

    def clean_land(self):
        land = self.cleaned_data.get("land")
        if land and land.status == Land.STATUS_SOLD:
            existing = getattr(land, "sale", None)
            if existing and existing.pk != self.instance.pk:
                raise forms.ValidationError(
                    f"Plot {land.plot_number} has already been sold to "
                    f"{existing.customer.full_name}."
                )
        return land

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get("selling_price")
        initial = cleaned.get("initial_payment") or Decimal("0.00")
        if price and initial and initial > price:
            self.add_error(
                "initial_payment",
                "The initial payment cannot be greater than the selling price.",
            )
        return cleaned


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    allow_overpayment = forms.BooleanField(
        label="Allow payment above the outstanding balance",
        required=False,
        help_text="Administrator override only.",
    )

    class Meta:
        model = Payment
        fields = ["sale", "amount", "payment_date", "payment_method", "notes"]
        widgets = {
            "payment_date": forms.DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, sale=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        queryset = Sale.objects.select_related("customer", "land")
        if sale is not None:
            queryset = queryset.filter(pk=sale.pk)
            self.initial["sale"] = sale.pk
        self.fields["sale"].queryset = queryset.order_by("-sale_date")
        self.fields["sale"].label_from_instance = (
            lambda s: f"{s.transaction_id} - {s.customer.full_name} "
                      f"(Plot {s.land.plot_number}, balance {currency(s.outstanding_balance)})"
        )
        if not self.instance.pk:
            # Never overwrite the saved date when editing an existing payment.
            self.fields["payment_date"].initial = timezone.localdate()
        self.fields["notes"].required = False

        from .models import get_profile

        profile = get_profile(user) if user else None
        if not (profile and profile.is_administrator):
            self.fields.pop("allow_overpayment", None)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Enter a payment amount greater than zero.")
        return amount

    def clean(self):
        cleaned = super().clean()
        sale = cleaned.get("sale")
        amount = cleaned.get("amount")
        if sale and amount:
            balance = sale.outstanding_balance
            if self.instance.pk:
                balance += self.instance.amount
            if amount > balance:
                override = cleaned.get("allow_overpayment", False)
                if not (override or Setting.get_bool("allow_overpayment")):
                    self.add_error(
                        "amount",
                        f"This payment exceeds the outstanding balance of "
                        f"{currency(balance)}. Reduce the amount or ask an "
                        f"administrator to allow the overpayment.",
                    )
        return cleaned


class PaymentRegisterForm(BootstrapFormMixin, forms.ModelForm):
    """One editable row of the payment register table.

    Used by :data:`PaymentRegisterFormSet` so a whole page of payments can be
    typed into, corrected and saved in a single table. The overpayment rules
    match :class:`PaymentForm`.
    """

    allow_overpayment = forms.BooleanField(
        label="Allow above balance",
        required=False,
        help_text="Administrator override only.",
    )

    class Meta:
        model = Payment
        fields = ["sale", "amount", "payment_date", "payment_method"]
        labels = {
            "sale": "Payment (customer / plot)",
            "amount": "Amount",
            "payment_date": "Date",
            "payment_method": "Method of receipt",
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["sale"].queryset = (
            Sale.objects.select_related("customer", "land").order_by("-sale_date")
        )
        self.fields["sale"].label_from_instance = (
            lambda s: f"{s.transaction_id} - {s.customer.full_name} "
                      f"(Plot {s.land.plot_number})"
        )
        self.fields["sale"].empty_label = "— choose a customer / plot —"
        self.fields["sale"].widget.attrs["class"] = "form-select form-select-sm"
        self.fields["amount"].widget.attrs.update(
            {
                "class": "form-control form-control-sm text-end",
                "step": "0.01",
                "min": "0.01",
                "inputmode": "decimal",
            }
        )
        self.fields["payment_date"].widget.attrs["class"] = (
            "form-control form-control-sm"
        )
        self.fields["payment_method"].widget.attrs["class"] = (
            "form-select form-select-sm"
        )
        # Only a brand new row defaults to today; existing rows keep their date.
        if not self.instance.pk:
            self.fields["payment_date"].initial = timezone.localdate()

        from .models import get_profile

        profile = get_profile(user) if user else None
        if not (profile and profile.is_administrator):
            self.fields.pop("allow_overpayment", None)

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Enter a payment amount greater than zero.")
        return amount

    def clean(self):
        cleaned = super().clean()
        sale = cleaned.get("sale")
        amount = cleaned.get("amount")
        if sale and amount:
            balance = sale.outstanding_balance
            if self.instance.pk:
                balance += self.instance.amount
            if amount > balance:
                override = cleaned.get("allow_overpayment", False)
                if not (override or Setting.get_bool("allow_overpayment")):
                    self.add_error(
                        "amount",
                        f"This payment exceeds the outstanding balance of "
                        f"{currency(balance)}. Reduce the amount or ask an "
                        f"administrator to allow the overpayment.",
                    )
        return cleaned


# Editable payment table: every row of the register is one of these forms.
PaymentRegisterFormSet = forms.modelformset_factory(
    Payment, form=PaymentRegisterForm, extra=2, can_delete=True
)


# ---------------------------------------------------------------------------
# Records table - the flat land-record grid
# ---------------------------------------------------------------------------
class LandRecordForm(BootstrapFormMixin, forms.ModelForm):
    """One editable row of the Records table.

    Every detail needed to keep a land sale record is on the row itself, so
    the table can be filled in without visiting other pages first.
    """

    TEXT_FIELDS = (
        "buyer_name", "phone", "id_number", "plot_number", "location",
    )
    MONEY_FIELDS = ("land_size", "total_price", "amount_paid")

    class Meta:
        model = LandRecord
        fields = [
            "record_date", "buyer_name", "phone", "id_number", "plot_number",
            "location", "land_size", "size_unit", "total_price", "amount_paid",
            "payment_method", "notes",
        ]
        labels = {
            "record_date": "Date",
            "buyer_name": "Buyer / customer",
            "phone": "Phone",
            "id_number": "Ghana card / ID",
            "plot_number": "Plot no.",
            "location": "Location / community",
            "land_size": "Size",
            "size_unit": "Unit",
            "total_price": "Total price",
            "amount_paid": "Amount paid",
            "payment_method": "Method of receipt",
            "notes": "Notes / details",
        }
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only styling here: which fields are required is decided by the model,
        # so an empty Buyer / customer name is always refused.
        for name in self.TEXT_FIELDS:
            self.fields[name].widget.attrs["class"] = "form-control form-control-sm"
        for name in self.MONEY_FIELDS:
            self.fields[name].widget.attrs.update(
                {
                    "class": "form-control form-control-sm text-end",
                    "step": "0.01",
                    "min": "0",
                    "inputmode": "decimal",
                }
            )
        self.fields["record_date"].widget.attrs["class"] = (
            "form-control form-control-sm"
        )
        self.fields["size_unit"].widget.attrs["class"] = "form-select form-select-sm"
        self.fields["payment_method"].widget.attrs["class"] = (
            "form-select form-select-sm"
        )
        self.fields["notes"].widget.attrs["class"] = "form-control form-control-sm"
        self.fields["buyer_name"].widget.attrs["placeholder"] = "Name of buyer"
        self.fields["phone"].widget.attrs["placeholder"] = "0244 000 000"
        self.fields["plot_number"].widget.attrs["placeholder"] = "e.g. 12A"
        self.fields["location"].widget.attrs["placeholder"] = "Town / community"
        if not self.instance.pk:
            self.fields["record_date"].initial = timezone.localdate()
            self.fields["amount_paid"].initial = Decimal("0.00")


# Five blank rows are always ready, and the table can add as many as needed.
LandRecordFormSet = forms.modelformset_factory(
    LandRecord, form=LandRecordForm, extra=5, can_delete=True
)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "document_type", "file", "customer", "land",
                  "sale", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.order_by("full_name")
        self.fields["customer"].label_from_instance = (
            lambda c: f"{c.full_name} ({c.customer_id})"
        )
        self.fields["land"].queryset = Land.objects.order_by("plot_number")
        self.fields["land"].label_from_instance = (
            lambda land: f"{land.land_id} - Plot {land.plot_number}, {land.location}"
        )
        self.fields["sale"].queryset = Sale.objects.select_related(
            "customer", "land"
        ).order_by("-sale_date")
        self.fields["sale"].label_from_instance = (
            lambda s: f"{s.transaction_id} - {s.customer.full_name}"
        )
        for name in ("customer", "land", "sale"):
            self.fields[name].required = False

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if upload is None:
            return upload
        extension = ""
        if "." in upload.name:
            extension = upload.name.rsplit(".", 1)[-1].lower()
        allowed = [ext.lower() for ext in settings.ALLOWED_DOCUMENT_EXTENSIONS]
        if extension not in allowed:
            raise forms.ValidationError(
                "Unsupported file type. Allowed: "
                + ", ".join(sorted(set(allowed))) + "."
            )
        if upload.size > settings.MAX_UPLOAD_SIZE:
            limit = settings.MAX_UPLOAD_SIZE // (1024 * 1024)
            raise forms.ValidationError(
                f"File is too large. Maximum allowed size is {limit} MB."
            )
        return upload

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(name) for name in ("customer", "land", "sale")):
            raise forms.ValidationError(
                "Link this document to at least one record "
                "(a customer, a land or a sale)."
            )
        return cleaned


# ---------------------------------------------------------------------------
# Users & settings (administrator only)
# ---------------------------------------------------------------------------
class UserForm(BootstrapFormMixin, forms.Form):
    """Create or edit a system user together with their role."""

    username = forms.CharField(max_length=150, label="Username")
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name", required=False)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=30, required=False)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    can_delete = forms.BooleanField(
        required=False,
        label="Allow deleting records",
        help_text="Staff only. Administrators and managers can always delete.",
    )
    is_active = forms.BooleanField(required=False, initial=True, label="Active")
    password1 = forms.CharField(
        label="Password", widget=forms.PasswordInput, required=False
    )
    password2 = forms.CharField(
        label="Confirm password", widget=forms.PasswordInput, required=False
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance is not None:
            from .models import get_profile

            profile = get_profile(instance)
            self.fields["username"].initial = instance.username
            self.fields["first_name"].initial = instance.first_name
            self.fields["last_name"].initial = instance.last_name
            self.fields["email"].initial = instance.email
            self.fields["is_active"].initial = instance.is_active
            if profile:
                self.fields["role"].initial = profile.role
                self.fields["phone"].initial = profile.phone
                self.fields["can_delete"].initial = profile.can_delete
            self.fields["password1"].help_text = "Leave blank to keep the current password."

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        duplicates = User.objects.filter(username__iexact=username)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean_phone(self):
        value = (self.cleaned_data.get("phone") or "").strip()
        if value:
            return validate_phone(value)
        return value

    def clean(self):
        from django.contrib.auth import password_validation

        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        if self.instance is None and not p1:
            self.add_error("password1", "A password is required for a new user.")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            elif p1:
                try:
                    password_validation.validate_password(p1)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self):
        from .models import get_profile

        data = self.cleaned_data
        user = self.instance or User()
        user.username = data["username"]
        user.first_name = data["first_name"]
        user.last_name = data.get("last_name", "")
        user.email = data.get("email", "")
        user.is_active = data.get("is_active", False)
        if data.get("password1"):
            user.set_password(data["password1"])
        elif not user.pk:
            user.set_unusable_password()
        user.save()

        profile = get_profile(user)
        profile.role = data["role"]
        profile.phone = data.get("phone", "")
        profile.can_delete = data.get("can_delete", False)
        profile.save()
        return user


class SettingsForm(BootstrapFormMixin, forms.Form):
    """Business/branding settings editable from the Settings page."""

    business_name = forms.CharField(max_length=150, label="Business name")
    business_phone = forms.CharField(max_length=30, label="Phone number", required=False)
    business_email = forms.EmailField(required=False)
    business_address = forms.CharField(max_length=200, required=False)
    currency_symbol = forms.CharField(max_length=10, label="Currency symbol")
    allow_overpayment = forms.BooleanField(
        required=False,
        label="Allow payments above the outstanding balance",
        help_text="When enabled, staff may record overpayments without an override.",
    )

    def clean_currency_symbol(self):
        value = (self.cleaned_data.get("currency_symbol") or "").strip().upper()
        if not value:
            raise forms.ValidationError("Enter a currency symbol, e.g. GHS.")
        return value

    def save(self):
        data = self.cleaned_data
        Setting.set("business_name", data["business_name"])
        Setting.set("business_phone", data.get("business_phone", ""))
        Setting.set("business_email", data.get("business_email", ""))
        Setting.set("business_address", data.get("business_address", ""))
        Setting.set("currency_symbol", data["currency_symbol"])
        Setting.set("allow_overpayment", "True" if data.get("allow_overpayment") else "False")