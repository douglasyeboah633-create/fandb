"""Views for the LandPro Records Management System.

Every view is protected by authentication and, where required, by role
based permission checks. All record changes are written to the audit trail.
"""

import json
import re
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import (
    admin_required,
    delete_permission_required,
    full_access_required,
    login_required_view,
)
from .forms import (
    CustomerForm,
    DocumentForm,
    LandForm,
    LandRecordFormSet,
    LoginForm,
    PaymentForm,
    PaymentRegisterFormSet,
    SaleForm,
    SettingsForm,
    UserForm,
)
from .models import (
    AuditLog,
    Customer,
    Document,
    Land,
    LandRecord,
    Payment,
    Sale,
    Setting,
    UserProfile,
    get_profile,
)
from .utils import (
    clean_filename,
    csv_response,
    currency,
    get_client_ip,
    money,
    parse_date,
    pdf_response,
    receipt_pdf_response,
    xlsx_response,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def log_action(request, action, obj=None, description=""):
    """Write an entry to the audit trail."""
    AuditLog.log(
        request.user, action, obj=obj,
        description=description, ip_address=get_client_ip(request),
    )


def paginate(request, queryset, per_page=15):
    """Paginate a queryset using the ``page`` query parameter."""
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get("page"))


def business_info():
    """Collect branding values used on receipts."""
    return {
        "name": Setting.get("business_name"),
        "phone": Setting.get("business_phone"),
        "email": Setting.get("business_email"),
        "address": Setting.get("business_address"),
        "currency": Setting.get("currency_symbol"),
    }


def period_range(request):
    """Return (start_date, end_date, label) from the period query parameters."""
    today = timezone.localdate()
    period = (request.GET.get("period") or "month").lower()

    if period == "today":
        return today, today, "Today"
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today, "This week"
    if period == "month":
        return today.replace(day=1), today, "This month"
    if period == "year":
        return today.replace(month=1, day=1), today, "This year"
    if period == "all":
        return None, None, "All records"

    start = parse_date(request.GET.get("start_date"))
    end = parse_date(request.GET.get("end_date"))
    if start or end:
        start = start or today.replace(month=1, day=1)
        end = end or today
        label = f"{start.strftime('%d %b %Y')} - {end.strftime('%d %b %Y')}"
        return start, end, label
    return today.replace(day=1), today, "This month"


def sales_queryset(start, end):
    """Sales filtered by an optional date range."""
    queryset = Sale.objects.select_related("customer", "land", "sales_agent")
    if start:
        queryset = queryset.filter(sale_date__gte=start)
    if end:
        queryset = queryset.filter(sale_date__lte=end)
    return queryset.order_by("-sale_date")


def payments_queryset(start, end):
    """Payments filtered by an optional date range."""
    queryset = Payment.objects.select_related(
        "sale__customer", "sale__land", "recorded_by"
    )
    if start:
        queryset = queryset.filter(payment_date__gte=start)
    if end:
        queryset = queryset.filter(payment_date__lte=end)
    return queryset.order_by("-payment_date", "-created_at")


def totals_for(queryset):
    """Return a (count, value) tuple for a sales queryset."""
    aggregate = queryset.aggregate(count=Count("id"), total=Sum("selling_price"))
    return aggregate["count"] or 0, aggregate["total"] or Decimal("0.00")


def sum_decimal(queryset, field_name):
    """Sum a decimal field, returning a Decimal (never None)."""
    return queryset.aggregate(total=Sum(field_name))["total"] or Decimal("0.00")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def home(request):
    """Send visitors to the records table or the login page."""
    if request.user.is_authenticated:
        return redirect("core:records")
    return redirect("core:login")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:records")

    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            log_action(request, AuditLog.ACTION_LOGIN, obj=user,
                       description="Signed in to the system.")
            messages.success(
                request,
                f"Welcome back, {user.get_full_name() or user.username}!",
            )
            return redirect("core:records")
        messages.error(request, "Login failed. Please check your details.")
    return render(request, "core/login.html", {"form": form})


def logout_view(request):
    if request.user.is_authenticated:
        log_action(request, AuditLog.ACTION_LOGOUT, obj=request.user,
                   description="Signed out of the system.")
        logout(request)
        messages.info(request, "You have been signed out.")
    return redirect("core:login")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def month_starts(count):
    """Return a list of the first day of the last ``count`` months."""
    today = timezone.localdate().replace(day=1)
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


def monthly_chart_data(months=6):
    """Build labels and values for the sales/payments trend chart."""
    starts = month_starts(months)

    sales_rows = (
        Sale.objects.annotate(month=TruncMonth("sale_date"))
        .values("month")
        .annotate(total=Sum("selling_price"), count=Count("id"))
    )
    payment_rows = (
        Payment.objects.annotate(month=TruncMonth("payment_date"))
        .values("month")
        .annotate(total=Sum("amount"))
    )

    sales_map = {}
    for row in sales_rows:
        key = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        sales_map[key.replace(day=1)] = row["total"] or Decimal("0.00")

    payments_map = {}
    for row in payment_rows:
        key = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        payments_map[key.replace(day=1)] = row["total"] or Decimal("0.00")

    labels = [start.strftime("%b %Y") for start in starts]
    return {
        "labels": labels,
        "sales": [float(sales_map.get(start, 0)) for start in starts],
        "payments": [float(payments_map.get(start, 0)) for start in starts],
    }


@login_required_view
def dashboard(request):
    lands = Land.objects.all()
    sales = Sale.objects.all()
    payments = Payment.objects.all()

    total_sales_value = sum_decimal(sales, "selling_price")
    total_received = sum_decimal(payments, "amount")

    stats = {
        "total_lands": lands.count(),
        "available_lands": lands.filter(status=Land.STATUS_AVAILABLE).count(),
        "sold_lands": lands.filter(status=Land.STATUS_SOLD).count(),
        "reserved_lands": lands.filter(status=Land.STATUS_RESERVED).count(),
        "total_customers": Customer.objects.count(),
        "total_sales": sales.count(),
        "total_sales_value": total_sales_value,
        "total_received": total_received,
        "outstanding": total_sales_value - total_received,
        "documents": Document.objects.count(),
    }

    paid_sales = [
        sale for sale in sales.only("selling_price") if sale.is_fully_paid
    ]
    stats["fully_paid_sales"] = len(paid_sales)
    stats["owing_sales"] = sales.count() - len(paid_sales)

    # Payment status breakdown for the doughnut chart.
    status_counts = {"Fully Paid": 0, "Partially Paid": 0, "Not Paid": 0}
    for sale in sales.prefetch_related("payments"):
        status_counts[sale.payment_status_display] += 1

    context = {
        "stats": stats,
        "land_status_labels": ["Available", "Reserved", "Sold"],
        "land_status_values": [
            stats["available_lands"], stats["reserved_lands"], stats["sold_lands"]
        ],
        "payment_status_labels": list(status_counts.keys()),
        "payment_status_values": list(status_counts.values()),
        "monthly": monthly_chart_data(),
        "recent_sales": Sale.objects.select_related("customer", "land")[:6],
        "recent_payments": Payment.objects.select_related(
            "sale__customer", "sale__land"
        )[:6],
        "recent_customers": Customer.objects.all()[:6],
        "top_locations": (
            lands.values("location")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        ),
    }
    return render(request, "core/dashboard.html", context)


# ---------------------------------------------------------------------------
# Customers / buyers
# ---------------------------------------------------------------------------

@login_required_view
def customer_list(request):
    query = (request.GET.get("q") or "").strip()
    customers = Customer.objects.all()
    if query:
        customers = customers.filter(
            Q(full_name__icontains=query)
            | Q(customer_id__icontains=query)
            | Q(phone__icontains=query)
            | Q(alt_phone__icontains=query)
            | Q(ghana_card__icontains=query)
            | Q(email__icontains=query)
            | Q(address__icontains=query)
        )
    page_obj = paginate(request, customers)
    return render(
        request,
        "core/customer_list.html",
        {"page_obj": page_obj, "query": query, "total": customers.count()},
    )


@login_required_view
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    sales = customer.sales.select_related("land").order_by("-sale_date")
    payments = Payment.objects.filter(sale__customer=customer).select_related(
        "sale__land", "recorded_by"
    )
    context = {
        "customer": customer,
        "sales": sales,
        "payments": payments,
        "documents": customer.documents.all(),
        "total_purchases": customer.total_purchases,
        "total_paid": customer.total_paid,
        "outstanding": customer.outstanding_balance,
    }
    return render(request, "core/customer_detail.html", context)


@login_required_view
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            customer = form.save(commit=False)
            customer.created_by = request.user
            customer.save()
            log_action(request, AuditLog.ACTION_CREATE, obj=customer,
                       description="Added a new customer.")
            messages.success(
                request, f"Customer {customer.full_name} was added successfully."
            )
            return redirect(customer.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/customer_form.html",
        {"form": form, "title": "Register customer", "is_edit": False},
    )


@login_required_view
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST":
        if form.is_valid():
            customer = form.save()
            log_action(request, AuditLog.ACTION_UPDATE, obj=customer,
                       description="Updated customer details.")
            messages.success(request, "Customer details were updated.")
            return redirect(customer.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/customer_form.html",
        {"form": form, "title": "Edit customer", "is_edit": True, "customer": customer},
    )


@login_required_view
@delete_permission_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect(customer.get_absolute_url())

    if customer.sales.exists():
        messages.error(
            request,
            f"{customer.full_name} has sales records and cannot be deleted. "
            "Delete or reassign those sales first.",
        )
        return redirect(customer.get_absolute_url())

    name = customer.full_name
    log_action(request, AuditLog.ACTION_DELETE, obj=customer,
               description=f"Deleted customer {name}.")
    customer.delete()
    messages.success(request, f"Customer {name} was deleted.")
    return redirect("core:customer_list")


# ---------------------------------------------------------------------------
# Land records
# ---------------------------------------------------------------------------

@login_required_view
def land_list(request):
    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    land_type = (request.GET.get("land_type") or "").strip()

    lands = Land.objects.select_related("assigned_staff", "sale__customer")
    if query:
        lands = lands.filter(
            Q(plot_number__icontains=query)
            | Q(block_number__icontains=query)
            | Q(land_id__icontains=query)
            | Q(location__icontains=query)
            | Q(region__icontains=query)
            | Q(district__icontains=query)
            | Q(community__icontains=query)
            | Q(gps_coordinates__icontains=query)
            | Q(description__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
            | Q(sale__customer__customer_id__icontains=query)
        )
    if status:
        lands = lands.filter(status=status)
    if land_type:
        lands = lands.filter(land_type=land_type)

    page_obj = paginate(request, lands)
    return render(
        request,
        "core/land_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "status": status,
            "land_type": land_type,
            "total": lands.count(),
            "status_choices": Land.STATUS_CHOICES,
            "type_choices": Land.TYPE_CHOICES,
        },
    )


@login_required_view
def land_detail(request, pk):
    land = get_object_or_404(
        Land.objects.select_related("assigned_staff", "created_by"), pk=pk
    )
    sale = getattr(land, "sale", None)
    context = {
        "land": land,
        "sale": sale,
        "payments": sale.payments.all() if sale else [],
        "documents": land.documents.all(),
    }
    return render(request, "core/land_detail.html", context)


@login_required_view
def land_create(request):
    form = LandForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            land = form.save(commit=False)
            land.created_by = request.user
            if not land.assigned_staff_id:
                land.assigned_staff = request.user
            land.save()
            log_action(request, AuditLog.ACTION_CREATE, obj=land,
                       description="Registered a new land record.")
            messages.success(
                request,
                f"Land {land.land_id} (Plot {land.plot_number}) was registered.",
            )
            return redirect(land.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/land_form.html",
        {"form": form, "title": "Register land", "is_edit": False},
    )


@login_required_view
def land_update(request, pk):
    land = get_object_or_404(Land, pk=pk)
    form = LandForm(request.POST or None, instance=land)
    if request.method == "POST":
        if form.is_valid():
            land = form.save()
            log_action(request, AuditLog.ACTION_UPDATE, obj=land,
                       description="Updated land details.")
            messages.success(request, "Land details were updated.")
            return redirect(land.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/land_form.html",
        {"form": form, "title": "Edit land", "is_edit": True, "land": land},
    )


@login_required_view
def land_set_status(request, pk, status):
    """Quick action: move a land between Available and Reserved."""
    land = get_object_or_404(Land, pk=pk)
    status = status.upper()
    if request.method != "POST":
        messages.warning(request, "Use the status buttons to change the status.")
        return redirect(land.get_absolute_url())

    if status not in {Land.STATUS_AVAILABLE, Land.STATUS_RESERVED}:
        messages.error(request, "That status change is not allowed here.")
        return redirect(land.get_absolute_url())

    if land.status == Land.STATUS_SOLD:
        messages.error(
            request,
            "This land has been sold. Delete the sale first to change its status.",
        )
        return redirect(land.get_absolute_url())

    land.status = status
    land.save(update_fields=["status", "updated_at"])
    log_action(request, AuditLog.ACTION_UPDATE, obj=land,
               description=f"Changed status to {land.get_status_display()}.")
    messages.success(
        request, f"Plot {land.plot_number} is now {land.get_status_display()}."
    )
    return redirect(land.get_absolute_url())


@login_required_view
@delete_permission_required
def land_delete(request, pk):
    land = get_object_or_404(Land, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect(land.get_absolute_url())

    if hasattr(land, "sale"):
        messages.error(
            request,
            f"{land.land_id} has a sale record and cannot be deleted. "
            "Delete the sale first.",
        )
        return redirect(land.get_absolute_url())

    label = f"{land.land_id} (Plot {land.plot_number})"
    log_action(request, AuditLog.ACTION_DELETE, obj=land,
               description=f"Deleted land {label}.")
    land.delete()
    messages.success(request, f"Land {label} was deleted.")
    return redirect("core:land_list")


# ---------------------------------------------------------------------------
# Sales / transactions
# ---------------------------------------------------------------------------

def sales_with_paid_annotation(queryset=None):
    """Annotate sales with the total amount paid (database side)."""
    queryset = queryset or Sale.objects.all()
    return queryset.annotate(
        paid=Coalesce(
            Sum("payments__amount"), Value(0),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )


@login_required_view
def sale_list(request):
    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    sales = sales_with_paid_annotation(
        Sale.objects.select_related("customer", "land", "sales_agent")
    )
    if query:
        sales = sales.filter(
            Q(transaction_id__icontains=query)
            | Q(customer__full_name__icontains=query)
            | Q(customer__customer_id__icontains=query)
            | Q(customer__phone__icontains=query)
            | Q(land__plot_number__icontains=query)
            | Q(land__land_id__icontains=query)
            | Q(land__location__icontains=query)
        )
    if status == Sale.STATUS_FULLY_PAID:
        sales = sales.filter(selling_price__lte=F("paid"))
    elif status == Sale.STATUS_PARTIAL:
        sales = sales.filter(paid__gt=0, selling_price__gt=F("paid"))
    elif status == Sale.STATUS_UNPAID:
        sales = sales.filter(paid=0)

    page_obj = paginate(request, sales.order_by("-sale_date", "-created_at"))
    return render(
        request,
        "core/sale_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "status": status,
            "total": sales.count(),
            "status_choices": [
                (Sale.STATUS_FULLY_PAID, "Fully Paid"),
                (Sale.STATUS_PARTIAL, "Partially Paid"),
                (Sale.STATUS_UNPAID, "Not Paid"),
            ],
        },
    )


@login_required_view
def sale_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("customer", "land", "sales_agent"), pk=pk
    )
    context = {
        "sale": sale,
        "payments": sale.payments.select_related("recorded_by"),
        "documents": sale.documents.all(),
    }
    return render(request, "core/sale_detail.html", context)


@login_required_view
def sale_create(request):
    form = SaleForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            sale = form.save(commit=False)
            sale.created_by = request.user
            if not sale.sales_agent_id:
                sale.sales_agent = request.user
            sale.save()

            initial = form.cleaned_data.get("initial_payment") or Decimal("0.00")
            if initial > 0:
                payment = Payment.objects.create(
                    sale=sale,
                    amount=initial,
                    payment_date=sale.sale_date,
                    payment_method=(
                        form.cleaned_data.get("initial_payment_method") or "CASH"
                    ),
                    recorded_by=request.user,
                    notes="Initial payment recorded with the sale.",
                )
                log_action(request, AuditLog.ACTION_CREATE, obj=payment,
                           description="Recorded the initial payment for a sale.")

            log_action(request, AuditLog.ACTION_CREATE, obj=sale,
                       description="Recorded a new land sale.")
            messages.success(
                request,
                f"Sale {sale.transaction_id} was recorded. "
                f"Plot {sale.land.plot_number} is now marked as Sold.",
            )
            return redirect(sale.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/sale_form.html",
        {"form": form, "title": "Record sale", "is_edit": False},
    )


@login_required_view
def sale_update(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    form = SaleForm(request.POST or None, instance=sale)
    if request.method == "POST":
        if form.is_valid():
            sale = form.save()
            log_action(request, AuditLog.ACTION_UPDATE, obj=sale,
                       description="Updated a sale record.")
            messages.success(request, "Sale details were updated.")
            return redirect(sale.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/sale_form.html",
        {"form": form, "title": "Edit sale", "is_edit": True, "sale": sale},
    )


@login_required_view
@delete_permission_required
def sale_delete(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect(sale.get_absolute_url())

    label = sale.transaction_id
    plot = sale.land.plot_number
    paid = sale.total_paid
    if paid > 0 and not request.POST.get("confirm_payments"):
        messages.error(
            request,
            f"Sale {label} has payments totalling {currency(paid)}. "
            "Deleting it will remove those payments too. "
            "Tick the confirmation box to continue.",
        )
        return redirect(sale.get_absolute_url())

    log_action(request, AuditLog.ACTION_DELETE, obj=sale,
               description=f"Deleted sale {label} (Plot {plot}).")
    sale.delete()  # signal releases the land back to 'Available'
    messages.success(
        request,
        f"Sale {label} was deleted and plot {plot} is available again.",
    )
    return redirect("core:sale_list")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@login_required_view
def payment_list(request):
    query = (request.GET.get("q") or "").strip()
    method = (request.GET.get("method") or "").strip()

    payments = Payment.objects.select_related(
        "sale__customer", "sale__land", "recorded_by"
    )
    if query:
        payments = payments.filter(
            Q(receipt_number__icontains=query)
            | Q(payment_id__icontains=query)
            | Q(sale__transaction_id__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
            | Q(sale__customer__customer_id__icontains=query)
            | Q(sale__customer__phone__icontains=query)
            | Q(sale__land__plot_number__icontains=query)
            | Q(sale__land__land_id__icontains=query)
        )
    if method:
        payments = payments.filter(payment_method=method)

    page_obj = paginate(request, payments.order_by("-payment_date", "-created_at"))
    return render(
        request,
        "core/payment_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "method": method,
            "total": payments.count(),
            "method_choices": Sale.PAYMENT_METHOD_CHOICES,
            "total_amount": sum_decimal(payments, "amount"),
        },
    )


# ---------------------------------------------------------------------------
# Payment register - one writable table with search
# ---------------------------------------------------------------------------

REGISTER_PAGE_SIZE = 20


def register_payments(query="", method=""):
    """Payments for the register, filtered by the search box, newest first."""
    payments = Payment.objects.select_related(
        "sale__customer", "sale__land", "recorded_by"
    )
    if query:
        payments = payments.filter(
            Q(receipt_number__icontains=query)
            | Q(payment_id__icontains=query)
            | Q(sale__transaction_id__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
            | Q(sale__customer__customer_id__icontains=query)
            | Q(sale__customer__phone__icontains=query)
            | Q(sale__customer__alt_phone__icontains=query)
            | Q(sale__land__plot_number__icontains=query)
            | Q(sale__land__land_id__icontains=query)
            | Q(sale__land__location__icontains=query)
        )
    if method:
        payments = payments.filter(payment_method=method)
    return payments.order_by("-payment_date", "-created_at")


@login_required_view
def payment_register(request):
    """A writable payment table.

    Search for a person, type straight into the rows, add or tick rows for
    removal, then save the whole page in one go.
    """
    query = (request.GET.get("q") or "").strip()
    method = (request.GET.get("method") or "").strip()
    profile = get_profile(request.user)

    payments = register_payments(query, method)
    total_shown = payments.count()
    total_amount = sum_decimal(payments, "amount")

    page_obj = paginate(request, payments, REGISTER_PAGE_SIZE)
    # A formset needs a real queryset (it re-orders it internally), and only
    # this page's rows may be edited, so restrict it to their primary keys.
    formset = PaymentRegisterFormSet(
        request.POST or None,
        queryset=Payment.objects.filter(
            pk__in=[payment.pk for payment in page_obj.object_list]
        ),
        prefix="row",
        form_kwargs={"user": request.user},
    )

    if request.method == "POST" and formset.is_valid():
        added = edited = removed = 0
        for payment in formset.save(commit=False):
            if payment.pk is None:
                payment.recorded_by = request.user
                added += 1
                action = AuditLog.ACTION_CREATE
                description = (
                    f"Added a payment of {currency(payment.amount)} for "
                    f"{payment.sale.transaction_id} "
                    f"(receipt {payment.receipt_number})."
                )
            else:
                edited += 1
                action = AuditLog.ACTION_UPDATE
                description = (
                    f"Updated payment {payment.payment_id} "
                    f"({currency(payment.amount)}) in the payment register."
                )
            # Deletions are deferred while saving without committing.
            if not payment.recorded_by_id:
                payment.recorded_by = request.user
            payment.save()
            log_action(request, action, obj=payment, description=description)

        if formset.deleted_objects:
            if profile.can_delete:
                for payment in formset.deleted_objects:
                    if not payment.pk:
                        continue
                    log_action(
                        request, AuditLog.ACTION_DELETE, obj=payment,
                        description=(
                            f"Deleted payment {payment.payment_id} "
                            f"({currency(payment.amount)}) from the register."
                        ),
                    )
                    payment.delete()
                    removed += 1
            else:
                messages.warning(
                    request,
                    "You do not have permission to delete payments, so the "
                    "ticked rows were kept. Ask an administrator for help.",
                )

        summary = [
            text for text in (
                f"{added} added" if added else "",
                f"{edited} updated" if edited else "",
                f"{removed} removed" if removed else "",
            ) if text
        ]
        messages.success(
            request,
            "Payment register saved"
            + (f" ({', '.join(summary)})." if summary else "."),
        )
        return redirect(request.get_full_path())

    page_amount = sum(
        (payment.amount for payment in page_obj.object_list), Decimal("0.00")
    )
    return render(
        request,
        "core/payment_register.html",
        {
            "formset": formset,
            "page_obj": page_obj,
            "query": query,
            "method": method,
            "total_shown": total_shown,
            "total_amount": total_amount,
            "page_amount": page_amount,
            "method_choices": Sale.PAYMENT_METHOD_CHOICES,
            "can_override": profile.is_administrator,
            "can_delete": profile.can_delete,
        },
    )


@login_required_view
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("sale__customer", "sale__land", "recorded_by"),
        pk=pk,
    )
    return render(request, "core/payment_detail.html", {"payment": payment})


@login_required_view
def payment_create(request):
    sale_id = request.GET.get("sale")
    sale = None
    if sale_id:
        try:
            sale_pk = int(sale_id)
            if not 0 < sale_pk <= 9223372036854775807:
                raise ValueError
        except (TypeError, ValueError):
            raise Http404("Sale not found.")
        sale = get_object_or_404(Sale, pk=sale_pk)

    form = PaymentForm(request.POST or None, user=request.user, sale=sale)
    if request.method == "POST":
        if form.is_valid():
            payment = form.save(commit=False)
            payment.recorded_by = request.user
            payment.save()
            log_action(
                request, AuditLog.ACTION_CREATE, obj=payment,
                description=(
                    f"Recorded a payment of {currency(payment.amount)} "
                    f"for {payment.sale.transaction_id} "
                    f"(receipt {payment.receipt_number})."
                ),
            )
            messages.success(
                request,
                f"Payment recorded. Receipt {payment.receipt_number} is ready.",
            )
            return redirect("core:receipt_print", pk=payment.pk)
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/payment_form.html",
        {"form": form, "title": "Record payment", "is_edit": False},
    )


@login_required_view
def payment_update(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    form = PaymentForm(request.POST or None, instance=payment, user=request.user)
    if request.method == "POST":
        if form.is_valid():
            payment = form.save()
            log_action(request, AuditLog.ACTION_UPDATE, obj=payment,
                       description="Updated a payment record.")
            messages.success(request, "Payment details were updated.")
            return redirect(payment.get_absolute_url())
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request, "core/payment_form.html",
        {"form": form, "title": "Edit payment", "is_edit": True, "payment": payment},
    )


@login_required_view
@delete_permission_required
def payment_delete(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect(payment.get_absolute_url())

    sale = payment.sale
    label = payment.receipt_number
    log_action(request, AuditLog.ACTION_DELETE, obj=payment,
               description=f"Deleted payment {label}.")
    payment.delete()
    messages.success(
        request,
        f"Payment {label} was deleted. The balance has been recalculated.",
    )
    return redirect(sale.get_absolute_url())


# ---------------------------------------------------------------------------
# Records - one flat, writable table for all record keeping
# ---------------------------------------------------------------------------

RECORD_PAGE_SIZES = [25, 50, 100, 200, 500]


def records_queryset(query="", method=""):
    """Records for the table, filtered by the search box, newest first."""
    records = LandRecord.objects.select_related("recorded_by")
    if query:
        records = records.filter(
            Q(record_number__icontains=query)
            | Q(receipt_number__icontains=query)
            | Q(buyer_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(id_number__icontains=query)
            | Q(plot_number__icontains=query)
            | Q(location__icontains=query)
            | Q(notes__icontains=query)
        )
    if method:
        records = records.filter(payment_method=method)
    return records.order_by("-record_date", "-created_at")


def _sum(values):
    return sum((value or Decimal("0.00") for value in values), Decimal("0.00"))


@login_required_view
def records(request):
    """The single record table.

    Search for a person, type straight into the rows, add as much space as
    needed with the add-row buttons or the "rows per page" control, then save
    the whole page in one go.
    """
    query = (request.GET.get("q") or "").strip()
    method = (request.GET.get("method") or "").strip()
    try:
        size = int(request.GET.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size not in RECORD_PAGE_SIZES:
        size = RECORD_PAGE_SIZES[0]

    profile = get_profile(request.user)
    matching = records_queryset(query, method)
    page_obj = paginate(request, matching, size)

    formset = LandRecordFormSet(
        request.POST or None,
        # A formset re-orders its queryset, and only this page's rows may be
        # edited, so it is restricted to their primary keys.
        queryset=LandRecord.objects.filter(
            pk__in=[row.pk for row in page_obj.object_list]
        ),
        prefix="rec",
    )

    if request.method == "POST" and formset.is_valid():
        added = edited = removed = 0
        added_numbers = []
        for record in formset.save(commit=False):
            is_new = record.pk is None
            if not record.recorded_by_id:
                record.recorded_by = request.user
            if is_new:
                added += 1
            else:
                edited += 1
            record.save()
            if is_new:
                added_numbers.append(record.record_number)
            log_action(
                request,
                AuditLog.ACTION_CREATE if is_new else AuditLog.ACTION_UPDATE,
                obj=record,
                description=(
                    f"Added record {record.record_number}: {record.buyer_name}, "
                    f"plot {record.plot_number or '—'}, "
                    f"{currency(record.amount_paid)} received "
                    f"(receipt {record.receipt_number})."
                    if is_new else
                    f"Updated record {record.record_number}: {record.buyer_name}, "
                    f"{currency(record.amount_paid)} received."
                ),
            )

        if formset.deleted_objects:
            if profile.can_delete:
                for record in formset.deleted_objects:
                    if not record.pk:
                        continue
                    log_action(
                        request, AuditLog.ACTION_DELETE, obj=record,
                        description=(
                            f"Deleted record {record.record_number} "
                            f"({record.buyer_name})."
                        ),
                    )
                    record.delete()
                    removed += 1
            else:
                messages.warning(
                    request,
                    "You do not have permission to delete records, so the "
                    "ticked rows were kept. Ask an administrator for help.",
                )

        summary = [
            text for text in (
                f"{added} added" if added else "",
                f"{edited} updated" if edited else "",
                f"{removed} removed" if removed else "",
            ) if text
        ]
        message = "Records saved"
        if summary:
            message += f" ({', '.join(summary)})"
        if added_numbers:
            message += ". New record number(s): " + ", ".join(added_numbers)
        if query or method:
            message += (
                ". Your search filter is active, so rows that do not match it are "
                "hidden from this page — click Clear to see every record."
            )
        messages.success(request, message + ".")
        return redirect(request.get_full_path())

    if request.method == "POST":
        # Nothing was written: say so loudly instead of appearing to save.
        problems = sum(1 for form in formset.forms if form.errors)
        messages.error(
            request,
            f"NOTHING WAS SAVED — {problems} row(s) need attention and are "
            "highlighted in red below. Correct them and click Save again. "
            "A row needs at least a Buyer / customer name, and the Amount paid "
            "cannot be more than the Total price.",
        )

    rows = list(page_obj.object_list)
    page_total = _sum(row.total_price for row in rows)
    page_paid = _sum(row.amount_paid for row in rows)
    overall = matching.aggregate(
        count=Count("id"), prices=Sum("total_price"), paid=Sum("amount_paid")
    )
    overall_total = overall["prices"] or Decimal("0.00")
    overall_paid = overall["paid"] or Decimal("0.00")

    return render(
        request,
        "core/records.html",
        {
            "formset": formset,
            "page_obj": page_obj,
            "query": query,
            "method": method,
            "size": size,
            "size_options": RECORD_PAGE_SIZES,
            "method_choices": LandRecord.PAYMENT_METHOD_CHOICES,
            "can_delete": profile.can_delete,
            "total_records": overall["count"] or 0,
            "total_price_all": overall_total,
            "total_paid_all": overall_paid,
            "total_balance_all": max(overall_total - overall_paid, Decimal("0.00")),
            "page_total": page_total,
            "page_paid": page_paid,
            "page_balance": max(page_total - page_paid, Decimal("0.00")),
        },
    )


@login_required_view
def record_receipt(request, pk):
    """Print one record of the table as a receipt."""
    record = get_object_or_404(
        LandRecord.objects.select_related("recorded_by"), pk=pk
    )
    return render(
        request,
        "core/record_receipt.html",
        {"record": record, "business": business_info()},
    )


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

@login_required_view
def receipt_list(request):
    query = (request.GET.get("q") or "").strip()
    payments = Payment.objects.select_related(
        "sale__customer", "sale__land", "recorded_by"
    )
    if query:
        payments = payments.filter(
            Q(receipt_number__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
            | Q(sale__customer__customer_id__icontains=query)
            | Q(sale__land__plot_number__icontains=query)
            | Q(sale__transaction_id__icontains=query)
        )
    page_obj = paginate(request, payments.order_by("-payment_date", "-created_at"))
    return render(
        request,
        "core/receipt_list.html",
        {"page_obj": page_obj, "query": query, "total": payments.count()},
    )


@login_required_view
def receipt_print(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("sale__customer", "sale__land", "recorded_by"),
        pk=pk,
    )
    context = {
        "payment": payment,
        "sale": payment.sale,
        "customer": payment.sale.customer,
        "land": payment.sale.land,
        "business": business_info(),
        "previous_balance": payment.sale.total_paid - payment.amount,
        "remaining_balance": payment.sale.outstanding_balance,
        "payment_status": payment.sale.payment_status_display,
    }
    return render(request, "core/receipt_print.html", context)


@login_required_view
def receipt_pdf(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("sale__customer", "sale__land", "recorded_by"),
        pk=pk,
    )
    log_action(request, AuditLog.ACTION_EXPORT, obj=payment,
               description=f"Downloaded receipt {payment.receipt_number} as PDF.")
    return receipt_pdf_response(payment, business_info())


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@login_required_view
def document_list(request):
    query = (request.GET.get("q") or "").strip()
    doc_type = (request.GET.get("type") or "").strip()

    documents = Document.objects.select_related(
        "customer", "land", "sale", "uploaded_by"
    )
    if query:
        documents = documents.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(customer__full_name__icontains=query)
            | Q(land__plot_number__icontains=query)
            | Q(land__land_id__icontains=query)
            | Q(sale__transaction_id__icontains=query)
        )
    if doc_type:
        documents = documents.filter(document_type=doc_type)

    page_obj = paginate(request, documents)
    return render(
        request,
        "core/document_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "doc_type": doc_type,
            "total": documents.count(),
            "type_choices": Document.TYPE_CHOICES,
        },
    )


@login_required_view
def document_create(request):
    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if form.is_valid():
            document = form.save(commit=False)
            document.uploaded_by = request.user
            document.save()
            log_action(request, AuditLog.ACTION_CREATE, obj=document,
                       description="Uploaded a document.")
            messages.success(request, "Document uploaded successfully.")
            return redirect("core:document_list")
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request,
        "core/document_form.html",
        {"form": form, "title": "Upload document"},
    )


@login_required_view
def document_download(request, pk):
    document = get_object_or_404(Document, pk=pk)
    try:
        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=document.file.name.split("/")[-1],
        )
    except FileNotFoundError:
        messages.error(request, "The file for this document could not be found.")
        return redirect("core:document_list")


@login_required_view
@delete_permission_required
def document_delete(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect("core:document_list")

    title = document.title
    try:
        document.file.delete(save=False)
    except Exception:  # pragma: no cover - file may already be missing
        pass
    log_action(request, AuditLog.ACTION_DELETE, obj=document,
               description=f"Deleted document {title}.")
    document.delete()
    messages.success(request, f"Document {title} was deleted.")
    return redirect("core:document_list")


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------

@login_required_view
def global_search(request):
    query = (request.GET.get("q") or "").strip()
    context = {"query": query}

    if query:
        customers = Customer.objects.filter(
            Q(full_name__icontains=query)
            | Q(customer_id__icontains=query)
            | Q(phone__icontains=query)
            | Q(alt_phone__icontains=query)
            | Q(ghana_card__icontains=query)
            | Q(email__icontains=query)
            | Q(address__icontains=query)
        )[:25]

        lands = Land.objects.select_related("sale__customer").filter(
            Q(plot_number__icontains=query)
            | Q(block_number__icontains=query)
            | Q(land_id__icontains=query)
            | Q(location__icontains=query)
            | Q(region__icontains=query)
            | Q(district__icontains=query)
            | Q(community__icontains=query)
            | Q(gps_coordinates__icontains=query)
            | Q(status__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
        )[:25]

        sales = Sale.objects.select_related("customer", "land").filter(
            Q(transaction_id__icontains=query)
            | Q(customer__full_name__icontains=query)
            | Q(customer__customer_id__icontains=query)
            | Q(customer__phone__icontains=query)
            | Q(land__plot_number__icontains=query)
            | Q(land__land_id__icontains=query)
            | Q(land__location__icontains=query)
        )[:25]

        payments = Payment.objects.select_related(
            "sale__customer", "sale__land"
        ).filter(
            Q(receipt_number__icontains=query)
            | Q(payment_id__icontains=query)
            | Q(sale__transaction_id__icontains=query)
            | Q(sale__customer__full_name__icontains=query)
            | Q(sale__customer__phone__icontains=query)
            | Q(sale__land__plot_number__icontains=query)
        )[:25]

        documents = Document.objects.select_related(
            "customer", "land", "sale"
        ).filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )[:25]

        context.update({
            "customers": customers,
            "lands": lands,
            "sales": sales,
            "payments": payments,
            "documents": documents,
            "total_results": (
                len(customers) + len(lands) + len(sales)
                + len(payments) + len(documents)
            ),
        })
    return render(request, "core/search.html", context)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

REPORT_INDEX = [
    {
        "key": "sales", "title": "Sales Report",
        "description": "All land sales with amounts paid and outstanding balances.",
        "icon": "bi-cart-check",
    },
    {
        "key": "payments", "title": "Payment Report",
        "description": "Every payment received with method and receipt number.",
        "icon": "bi-cash-coin",
    },
    {
        "key": "outstanding", "title": "Outstanding Balance Report",
        "description": "Customers who still owe money on their land purchases.",
        "icon": "bi-exclamation-diamond",
    },
    {
        "key": "available_lands", "title": "Available Land Report",
        "description": "All land plots that are still available for sale.",
        "icon": "bi-map",
    },
    {
        "key": "sold_lands", "title": "Sold Land Report",
        "description": "All land plots that have been sold.",
        "icon": "bi-house-check",
    },
    {
        "key": "customers", "title": "Customer Report",
        "description": "Customer registrations with purchase and balance totals.",
        "icon": "bi-people",
    },
    {
        "key": "monthly", "title": "Monthly Report",
        "description": "Sales, payments and balances grouped by month.",
        "icon": "bi-calendar3",
    },
]


@login_required_view
def reports_index(request):
    return render(request, "core/reports_index.html", {"reports": REPORT_INDEX})


def report_sales(start, end):
    queryset = sales_queryset(start, end)
    headers = ["Date", "Transaction", "Customer", "Plot", "Location",
               "Selling price", "Amount paid", "Balance", "Payment status"]
    rows = []
    total_value = Decimal("0.00")
    total_paid = Decimal("0.00")
    for sale in queryset:
        rows.append([
            sale.sale_date.strftime("%d %b %Y"),
            sale.transaction_id,
            sale.customer.full_name,
            sale.land.plot_number,
            sale.land.location,
            money(sale.selling_price),
            money(sale.total_paid),
            money(sale.outstanding_balance),
            sale.payment_status_display,
        ])
        total_value += sale.selling_price
        total_paid += sale.total_paid
    summary = (
        f"<b>{len(rows)}</b> sale(s) | Total value: "
        f"<b>{currency(total_value)}</b> | Received: "
        f"<b>{currency(total_paid)}</b> | Outstanding: "
        f"<b>{currency(total_value - total_paid)}</b>"
    )
    return {
        "title": "Sales Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {5, 6, 7},
    }


def report_payments(start, end):
    queryset = payments_queryset(start, end)
    headers = ["Date", "Receipt", "Transaction", "Customer", "Plot",
               "Amount", "Method", "Recorded by"]
    rows = []
    for payment in queryset:
        rows.append([
            payment.payment_date.strftime("%d %b %Y"),
            payment.receipt_number,
            payment.sale.transaction_id,
            payment.sale.customer.full_name,
            payment.sale.land.plot_number,
            money(payment.amount),
            payment.method_display,
            (payment.recorded_by.get_full_name() or payment.recorded_by.username)
            if payment.recorded_by else "-",
        ])
    total = sum_decimal(queryset, "amount")
    summary = f"<b>{len(rows)}</b> payment(s) | Total received: <b>{currency(total)}</b>"
    return {
        "title": "Payment Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {5},
    }


def report_outstanding(start, end):
    queryset = sales_queryset(start, end)
    headers = ["Customer", "Customer ID", "Phone", "Plot", "Location",
               "Selling price", "Paid", "Balance owed", "Status"]
    rows = []
    total_owed = Decimal("0.00")
    for sale in queryset:
        balance = sale.outstanding_balance
        if balance <= 0:
            continue
        total_owed += balance
        rows.append([
            sale.customer.full_name,
            sale.customer.customer_id,
            sale.customer.phone,
            sale.land.plot_number,
            sale.land.location,
            money(sale.selling_price),
            money(sale.total_paid),
            money(balance),
            sale.payment_status_display,
        ])
    summary = (
        f"<b>{len(rows)}</b> customer(s) owing | Total outstanding: "
        f"<b>{currency(total_owed)}</b>"
    )
    return {
        "title": "Outstanding Balance Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {5, 6, 7},
    }


def report_available_lands(start, end):
    queryset = Land.objects.filter(
        status=Land.STATUS_AVAILABLE
    ).order_by("plot_number")
    if start:
        queryset = queryset.filter(date_added__gte=start)
    if end:
        queryset = queryset.filter(date_added__lte=end)
    headers = ["Land ID", "Plot", "Block", "Location", "Type", "Size",
               "Price", "Status", "Date added"]
    rows = [
        [
            land.land_id, land.plot_number, land.block_number or "-",
            land.location, land.get_land_type_display(),
            f"{land.land_size} {land.get_size_unit_display()}",
            money(land.price), land.get_status_display(),
            land.date_added.strftime("%d %b %Y"),
        ]
        for land in queryset
    ]
    total_value = sum_decimal(queryset, "price")
    summary = (
        f"<b>{len(rows)}</b> available plot(s) | Total value: "
        f"<b>{currency(total_value)}</b>"
    )
    return {
        "title": "Available Land Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {6},
    }


def report_sold_lands(start, end):
    queryset = Land.objects.filter(status=Land.STATUS_SOLD).select_related(
        "sale__customer"
    ).order_by("plot_number")
    headers = ["Land ID", "Plot", "Location", "Size", "Price",
               "Buyer", "Sale date", "Paid", "Balance"]
    rows = []
    total_value = Decimal("0.00")
    for land in queryset:
        sale = getattr(land, "sale", None)
        rows.append([
            land.land_id, land.plot_number, land.location,
            f"{land.land_size} {land.get_size_unit_display()}",
            money(land.price),
            sale.customer.full_name if sale else "-",
            sale.sale_date.strftime("%d %b %Y") if sale else "-",
            money(sale.total_paid) if sale else "-",
            money(sale.outstanding_balance) if sale else "-",
        ])
        if sale:
            total_value += sale.selling_price
    summary = (
        f"<b>{len(rows)}</b> sold plot(s) | Total sales value: "
        f"<b>{currency(total_value)}</b>"
    )
    return {
        "title": "Sold Land Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {4, 7, 8},
    }


def report_customers(start, end):
    queryset = Customer.objects.all()
    if start:
        queryset = queryset.filter(date_registered__gte=start)
    if end:
        queryset = queryset.filter(date_registered__lte=end)
    headers = ["Customer ID", "Full name", "Phone", "Ghana Card", "Email",
               "Registered", "Purchases", "Total paid", "Balance"]
    rows = [
        [
            customer.customer_id, customer.full_name, customer.phone,
            customer.ghana_card or "-", customer.email or "-",
            customer.date_registered.strftime("%d %b %Y"),
            money(customer.total_purchases), money(customer.total_paid),
            money(customer.outstanding_balance),
        ]
        for customer in queryset
    ]
    summary = f"<b>{len(rows)}</b> registered customer(s)"
    return {
        "title": "Customer Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {6, 7, 8},
    }


def report_monthly(start, end):
    sales_rows = (
        Sale.objects.annotate(month=TruncMonth("sale_date"))
        .values("month")
        .annotate(count=Count("id"), total=Sum("selling_price"))
        .order_by("month")
    )
    payment_rows = (
        Payment.objects.annotate(month=TruncMonth("payment_date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    payments_map = {}
    for row in payment_rows:
        key = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        payments_map[key.replace(day=1)] = row["total"] or Decimal("0.00")

    headers = ["Month", "Sales", "Total sales value", "Payments received",
               "Outstanding balance"]
    rows = []
    totals = {"count": 0, "value": Decimal("0.00"), "paid": Decimal("0.00")}
    for row in sales_rows:
        key = row["month"].date() if hasattr(row["month"], "date") else row["month"]
        key = key.replace(day=1)
        if start and key < start.replace(day=1):
            continue
        if end and key > end:
            continue
        paid = payments_map.get(key, Decimal("0.00"))
        value = row["total"] or Decimal("0.00")
        rows.append([
            key.strftime("%B %Y"), row["count"], money(value),
            money(paid), money(max(value - paid, Decimal("0.00"))),
        ])
        totals["count"] += row["count"]
        totals["value"] += value
        totals["paid"] += paid

    summary = (
        f"<b>{totals['count']}</b> sale(s) in {len(rows)} month(s) | Sales value: "
        f"<b>{currency(totals['value'])}</b> | Received: "
        f"<b>{currency(totals['paid'])}</b> | Outstanding: "
        f"<b>{currency(totals['value'] - totals['paid'])}</b>"
    )
    return {
        "title": "Monthly Report", "headers": headers, "rows": rows,
        "summary": summary, "numeric": {1, 2, 3, 4},
    }


REPORT_BUILDERS = {
    "sales": report_sales,
    "payments": report_payments,
    "outstanding": report_outstanding,
    "available_lands": report_available_lands,
    "sold_lands": report_sold_lands,
    "customers": report_customers,
    "monthly": report_monthly,
}


@login_required_view
def report_view(request, kind):
    builder = REPORT_BUILDERS.get(kind)
    if builder is None:
        messages.error(request, "That report could not be found.")
        return redirect("core:reports_index")

    start, end, label = period_range(request)
    data = builder(start, end)
    export = (request.GET.get("export") or "").lower()
    subtitle = f"Period: {label}."
    slug = clean_filename(data["title"])

    if export in {"csv", "xlsx", "pdf"}:
        log_action(
            request, AuditLog.ACTION_EXPORT,
            description=f"Exported the {data['title']} for {label} as {export.upper()}.",
        )
        if export == "csv":
            return csv_response(slug, data["headers"], data["rows"])
        if export == "xlsx":
            return xlsx_response(
                slug, data["title"], data["headers"], data["rows"]
            )
        plain_summary = re.sub(r"<[^>]+>", "", data["summary"])
        return pdf_response(
            slug, data["title"], data["headers"], data["rows"],
            subtitle=subtitle, summary=plain_summary,
            numeric_columns=data["numeric"],
        )

    context = {
        "report": data,
        "kind": kind,
        "label": label,
        "period": request.GET.get("period") or "month",
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
    }
    return render(request, "core/report_detail.html", context)


# ---------------------------------------------------------------------------
# Activity / audit log
# ---------------------------------------------------------------------------

@login_required_view
@full_access_required
def audit_log_list(request):
    query = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()

    logs = AuditLog.objects.select_related("user")
    if query:
        logs = logs.filter(
            Q(object_repr__icontains=query)
            | Q(description__icontains=query)
            | Q(model_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
        )
    if action:
        logs = logs.filter(action=action)

    page_obj = paginate(request, logs, per_page=25)
    return render(
        request,
        "core/audit_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "action": action,
            "action_choices": AuditLog.ACTION_CHOICES,
            "total": logs.count(),
        },
    )


# ---------------------------------------------------------------------------
# User management (administrators only)
# ---------------------------------------------------------------------------

def _admin_count():
    return UserProfile.objects.filter(
        role=UserProfile.ROLE_ADMIN, user__is_active=True
    ).count()


@login_required_view
@admin_required
def user_list(request):
    query = (request.GET.get("q") or "").strip()
    users = User.objects.select_related("profile").order_by("first_name", "username")
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(profile__phone__icontains=query)
        )
    page_obj = paginate(request, users)
    return render(
        request,
        "core/user_list.html",
        {"page_obj": page_obj, "query": query, "total": users.count()},
    )


@login_required_view
@admin_required
def user_create(request):
    form = UserForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            user = form.save()
            log_action(request, AuditLog.ACTION_CREATE, obj=user,
                       description=f"Created the user account {user.username}.")
            messages.success(request, f"User {user.username} was created.")
            return redirect("core:user_list")
        messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request,
        "core/user_form.html",
        {"form": form, "title": "Add user", "is_edit": False},
    )


@login_required_view
@admin_required
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    profile = get_profile(user)
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST":
        if form.is_valid():
            if (profile.role == UserProfile.ROLE_ADMIN
                    and form.cleaned_data["role"] != UserProfile.ROLE_ADMIN
                    and _admin_count() <= 1):
                messages.error(
                    request,
                    "You cannot remove the last administrator. "
                    "Create another administrator first.",
                )
            elif not form.cleaned_data.get("is_active") and user == request.user:
                messages.error(request, "You cannot deactivate your own account.")
            else:
                user = form.save()
                log_action(request, AuditLog.ACTION_UPDATE, obj=user,
                           description=f"Updated the user account {user.username}.")
                messages.success(request, "User details were updated.")
                return redirect("core:user_list")
        else:
            messages.error(request, "Please correct the highlighted fields below.")
    return render(
        request,
        "core/user_form.html",
        {"form": form, "title": "Edit user", "is_edit": True, "edit_user": user},
    )


@login_required_view
@admin_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        messages.warning(request, "Use the delete button to confirm this action.")
        return redirect("core:user_list")

    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("core:user_list")

    profile = get_profile(user)
    if profile and profile.role == UserProfile.ROLE_ADMIN and _admin_count() <= 1:
        messages.error(
            request, "You cannot delete the last administrator account."
        )
        return redirect("core:user_list")

    username = user.username
    log_action(request, AuditLog.ACTION_DELETE, obj=user,
               description=f"Deleted the user account {username}.")
    user.delete()
    messages.success(request, f"User {username} was deleted.")
    return redirect("core:user_list")


# ---------------------------------------------------------------------------
# Settings & data backup (administrators only)
# ---------------------------------------------------------------------------

@login_required_view
@admin_required
def settings_view(request):
    initial = {
        "business_name": Setting.get("business_name"),
        "business_phone": Setting.get("business_phone"),
        "business_email": Setting.get("business_email"),
        "business_address": Setting.get("business_address"),
        "currency_symbol": Setting.get("currency_symbol"),
        "allow_overpayment": Setting.get_bool("allow_overpayment"),
    }
    form = SettingsForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            log_action(request, AuditLog.ACTION_UPDATE,
                       description="Updated the business settings.")
            messages.success(request, "Settings were saved successfully.")
            return redirect("core:settings")
        messages.error(request, "Please correct the highlighted fields below.")

    context = {
        "form": form,
        "title": "Business settings",
        "stats": {
            "customers": Customer.objects.count(),
            "lands": Land.objects.count(),
            "sales": Sale.objects.count(),
            "payments": Payment.objects.count(),
            "documents": Document.objects.count(),
            "users": User.objects.count(),
            "audit_entries": AuditLog.objects.count(),
        },
    }
    return render(request, "core/settings.html", context)


def _backup_payload():
    """Build a complete, restorable snapshot of the important records."""
    return {
        "application": "LandPro Records Management System",
        "generated_at": timezone.localtime().isoformat(),
        "business": business_info(),
        "counts": {
            "customers": Customer.objects.count(),
            "lands": Land.objects.count(),
            "sales": Sale.objects.count(),
            "payments": Payment.objects.count(),
            "documents": Document.objects.count(),
            "users": User.objects.count(),
        },
        "customers": [
            {
                "customer_id": c.customer_id, "full_name": c.full_name,
                "ghana_card": c.ghana_card, "phone": c.phone,
                "alt_phone": c.alt_phone, "email": c.email,
                "address": c.address, "occupation": c.occupation,
                "date_registered": c.date_registered.isoformat(),
                "next_of_kin": c.next_of_kin,
                "next_of_kin_phone": c.next_of_kin_phone, "notes": c.notes,
            }
            for c in Customer.objects.all()
        ],
        "lands": [
            {
                "land_id": land.land_id, "plot_number": land.plot_number,
                "block_number": land.block_number, "location": land.location,
                "region": land.region, "district": land.district,
                "community": land.community, "land_size": str(land.land_size),
                "size_unit": land.size_unit, "land_type": land.land_type,
                "price": str(land.price), "status": land.status,
                "date_added": land.date_added.isoformat(),
                "description": land.description,
                "gps_coordinates": land.gps_coordinates,
                "assigned_staff": (
                    land.assigned_staff.username if land.assigned_staff else None
                ),
                "notes": land.notes,
            }
            for land in Land.objects.all()
        ],
        "sales": [
            {
                "transaction_id": s.transaction_id,
                "customer_id": s.customer.customer_id,
                "land_id": s.land.land_id,
                "selling_price": str(s.selling_price),
                "sale_date": s.sale_date.isoformat(),
                "sales_agent": (s.sales_agent.username if s.sales_agent else None),
                "payment_method": s.payment_method,
                "notes": s.notes,
                "total_paid": str(s.total_paid),
                "outstanding_balance": str(s.outstanding_balance),
                "payment_status": s.payment_status_display,
            }
            for s in Sale.objects.select_related("customer", "land")
        ],
        "payments": [
            {
                "payment_id": p.payment_id,
                "receipt_number": p.receipt_number,
                "transaction_id": p.sale.transaction_id,
                "amount": str(p.amount),
                "payment_date": p.payment_date.isoformat(),
                "payment_method": p.payment_method,
                "recorded_by": (p.recorded_by.username if p.recorded_by else None),
                "notes": p.notes,
            }
            for p in Payment.objects.select_related("sale")
        ],
        "documents": [
            {
                "title": d.title, "document_type": d.document_type,
                "file": d.file.name if d.file else "",
                "customer": d.customer.customer_id if d.customer else None,
                "land": d.land.land_id if d.land else None,
                "sale": d.sale.transaction_id if d.sale else None,
                "description": d.description,
                "uploaded_at": d.uploaded_at.isoformat(),
            }
            for d in Document.objects.select_related("customer", "land", "sale")
        ],
        "users": [
            {
                "username": u.username, "first_name": u.first_name,
                "last_name": u.last_name, "email": u.email,
                "is_active": u.is_active,
                "role": getattr(get_profile(u), "role", "STAFF"),
            }
            for u in User.objects.all()
        ],
    }


def _backup_rows(table):
    """Return (headers, rows) for a single CSV backup table."""
    if table == "customers":
        headers = ["Customer ID", "Full name", "Ghana Card", "Phone",
                   "Alt phone", "Email", "Address", "Occupation",
                   "Registered", "Next of kin", "Next of kin phone", "Notes"]
        rows = [
            [c.customer_id, c.full_name, c.ghana_card or "", c.phone,
             c.alt_phone, c.email, c.address, c.occupation,
             c.date_registered, c.next_of_kin, c.next_of_kin_phone, c.notes]
            for c in Customer.objects.all()
        ]
        return headers, rows

    if table == "lands":
        headers = ["Land ID", "Plot", "Block", "Location", "Region", "District",
                   "Community", "Size", "Unit", "Type", "Price", "Status",
                   "Date added", "GPS", "Notes"]
        rows = [
            [land.land_id, land.plot_number, land.block_number, land.location,
             land.region, land.district, land.community, land.land_size,
             land.size_unit, land.land_type, land.price, land.status,
             land.date_added, land.gps_coordinates, land.notes]
            for land in Land.objects.all()
        ]
        return headers, rows

    if table == "sales":
        headers = ["Transaction ID", "Customer", "Customer ID", "Land ID",
                   "Plot", "Location", "Selling price", "Sale date",
                   "Agent", "Payment status"]
        rows = [
            [s.transaction_id, s.customer.full_name, s.customer.customer_id,
             s.land.land_id, s.land.plot_number, s.land.location,
             s.selling_price, s.sale_date,
             (s.sales_agent.username if s.sales_agent else ""),
             s.payment_status_display]
            for s in Sale.objects.select_related("customer", "land", "sales_agent")
        ]
        return headers, rows

    if table == "payments":
        headers = ["Payment ID", "Receipt", "Transaction", "Customer", "Plot",
                   "Amount", "Date", "Method", "Recorded by"]
        rows = [
            [p.payment_id, p.receipt_number, p.sale.transaction_id,
             p.sale.customer.full_name, p.sale.land.plot_number, p.amount,
             p.payment_date, p.payment_method,
             (p.recorded_by.username if p.recorded_by else "")]
            for p in Payment.objects.select_related(
                "sale__customer", "sale__land", "recorded_by"
            )
        ]
        return headers, rows

    if table == "audit_logs":
        headers = ["Date", "User", "Action", "Record", "Description", "IP"]
        rows = [
            [log.created_at, (log.user.username if log.user else "system"),
             log.get_action_display(), log.object_repr, log.description,
             log.ip_address or ""]
            for log in AuditLog.objects.select_related("user")
        ]
        return headers, rows

    return [], []


@login_required_view
@admin_required
def backup_view(request):
    export = (request.GET.get("export") or "").lower()
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M")

    if export == "json":
        payload = _backup_payload()
        response = HttpResponse(
            json.dumps(payload, indent=2, default=str),
            content_type="application/json",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="landpro_backup_{stamp}.json"'
        )
        log_action(request, AuditLog.ACTION_BACKUP,
                   description="Downloaded a full JSON backup of all records.")
        messages.success(request, "Your backup file has been downloaded.")
        return response

    if export in {"customers", "lands", "sales", "payments", "audit_logs"}:
        headers, rows = _backup_rows(export)
        log_action(request, AuditLog.ACTION_BACKUP,
                   description=f"Downloaded a {export} backup (CSV).")
        return csv_response(f"landpro_{export}", headers, rows)

    context = {
        "last_entries": AuditLog.objects.select_related("user")[:10],
        "counts": {
            "customers": Customer.objects.count(),
            "lands": Land.objects.count(),
            "sales": Sale.objects.count(),
            "payments": Payment.objects.count(),
            "documents": Document.objects.count(),
        },
    }
    return render(request, "core/backup.html", context)


# ---------------------------------------------------------------------------
# Friendly error pages
# ---------------------------------------------------------------------------

def _error(request, code, title, message):
    return render(
        request,
        "core/error.html",
        {"code": code, "title": title, "message": message},
        status=code,
    )


def error_400(request, exception=None):
    return _error(
        request, 400, "Bad request",
        "We could not process that request. Please check your details and try again.",
    )


def error_403(request, exception=None):
    return _error(
        request, 403, "Access denied",
        "You do not have permission to view that page. "
        "Please contact your administrator if you believe this is a mistake.",
    )


def error_404(request, exception=None):
    return _error(
        request, 404, "Record not found",
        "The page or record you are looking for does not exist "
        "or may have been deleted.",
    )


def error_500(request):
    return _error(
        request, 500, "Something went wrong",
        "An unexpected error occurred. Your records are safe. "
        "Please try again, and contact your administrator if the problem continues.",
    )
