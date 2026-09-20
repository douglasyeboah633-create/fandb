"""Repeatable template, permissions, export and business-workflow checks."""
from decimal import Decimal
from io import StringIO
from pathlib import Path
import re
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template.loader import get_template
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import views
from .forms import PaymentForm
from .models import (
    AuditLog,
    Customer,
    Document,
    Land,
    LandRecord,
    Payment,
    Sale,
    UserProfile,
    get_profile,
)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ApplicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", stdout=StringIO())
        cls.admin = User.objects.get(username="admin")
        cls.staff = User.objects.get(username="staff")
        cls.manager = User.objects.get(username="manager")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_every_template_compiles_and_view_templates_exist(self):
        root = settings.BASE_DIR / "templates"
        for path in root.rglob("*.html"):
            with self.subTest(template=str(path)):
                get_template(path.relative_to(root).as_posix())
        source = Path(views.__file__).read_text(encoding="utf-8")
        for name in set(re.findall(r'"(core/[^"\n]+\.html)"', source)):
            with self.subTest(view_template=name):
                get_template(name)

    def test_authenticated_pages_and_edit_forms(self):
        names = ["records", "dashboard", "customer_list", "land_list", "sale_list",
                 "payment_list", "receipt_list", "document_list", "reports_index",
                 "audit_list", "user_list", "settings", "backup", "search",
                 "customer_create", "land_create", "sale_create", "payment_create",
                 "document_create", "user_create"]
        for name in names:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse("core:" + name)).status_code, 200)
        for prefix, model in [("customer", Customer), ("land", Land),
                              ("sale", Sale), ("payment", Payment)]:
            for suffix in ["detail", "update"]:
                with self.subTest(page=prefix + suffix):
                    response = self.client.get(reverse(f"core:{prefix}_{suffix}", args=[model.objects.first().pk]))
                    self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("core:user_update", args=[self.staff.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:receipt_print", args=[Payment.objects.first().pk])).status_code, 200)
        response = self.client.get(reverse("core:search"), {"q": Customer.objects.first().full_name})
        self.assertContains(response, Customer.objects.first().full_name)

    def test_reports_and_exports(self):
        for kind in views.REPORT_BUILDERS:
            for export in ["", "csv", "xlsx", "pdf"]:
                with self.subTest(report=kind, export=export):
                    response = self.client.get(reverse("core:report_view", args=[kind]), {"period": "all", "export": export})
                    self.assertEqual(response.status_code, 200)
                    if export == "pdf":
                        self.assertTrue(response.content.startswith(b"%PDF"))
                    elif export == "xlsx":
                        self.assertTrue(response.content.startswith(b"PK"))
        receipt = self.client.get(reverse("core:receipt_pdf", args=[Payment.objects.first().pk]))
        self.assertTrue(receipt.content.startswith(b"%PDF"))
        for export in ["json", "customers", "lands", "sales", "payments", "audit_logs"]:
            self.assertEqual(self.client.get(reverse("core:backup"), {"export": export}).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_EXPORT).exists())

    def test_permissions_and_csrf(self):
        for user, denied in [(self.staff, ["audit_list", "user_list", "settings", "backup"]),
                             (self.manager, ["user_list", "settings", "backup"])]:
            self.client.force_login(user)
            for name in denied:
                self.assertRedirects(self.client.get(reverse("core:" + name)), reverse("core:dashboard"))
        self.client.force_login(self.staff)
        customer = Customer.objects.first()
        self.client.post(reverse("core:customer_delete", args=[customer.pk]))
        self.assertTrue(Customer.objects.filter(pk=customer.pk).exists())
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.admin)
        self.assertEqual(secure_client.post(reverse("core:customer_create"), {}).status_code, 403)

    def test_error_pages(self):
        self.assertContains(self.client.get("/not-a-landpro-route/"), "Record not found", status_code=404)
        from django.test import RequestFactory
        for code in [400, 403, 404, 500]:
            response = getattr(views, f"error_{code}")(RequestFactory().get("/"))
            self.assertEqual(response.status_code, code)

    def test_sale_payment_workflow(self):
        customer = Customer.objects.first()
        land = Land.objects.filter(sale__isnull=True).first()
        response = self.client.post(reverse("core:sale_create"), {
            "customer": customer.pk, "land": land.pk, "selling_price": "1000.00",
            "sale_date": "2026-09-01", "payment_method": "CASH",
            "initial_payment": "250.00", "initial_payment_method": "CASH",
        })
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get(land=land)
        land.refresh_from_db()
        self.assertEqual(land.status, Land.STATUS_SOLD)
        self.assertEqual(sale.total_paid, Decimal("250.00"))
        self.assertEqual(sale.outstanding_balance, Decimal("750.00"))
        self.assertEqual(sale.payment_status, Sale.STATUS_PARTIAL)
        self.client.force_login(self.staff)
        payload = {"sale": sale.pk, "amount": "751.00", "payment_date": "2026-09-02", "payment_method": "CASH"}
        response = self.client.post(reverse("core:payment_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("amount", response.context["form"].errors)
        self.assertEqual(sale.payments.count(), 1)
        payload["amount"] = "750.00"
        response = self.client.post(reverse("core:payment_create"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sale.total_paid, Decimal("1000.00"))
        self.assertEqual(sale.outstanding_balance, Decimal("0.00"))
        self.assertEqual(sale.payment_status, Sale.STATUS_FULLY_PAID)
        self.client.force_login(self.admin)
        self.client.post(reverse("core:sale_delete", args=[sale.pk]))
        self.assertTrue(Sale.objects.filter(pk=sale.pk).exists())
        self.client.post(reverse("core:sale_delete", args=[sale.pk]), {"confirm_payments": "on"})
        land.refresh_from_db()
        self.assertEqual(land.status, Land.STATUS_AVAILABLE)
        self.assertFalse(Payment.objects.filter(sale_id=sale.pk).exists())

    def test_payment_preselection_and_override_roles(self):
        sale = Sale.objects.first()
        response = self.client.get(reverse("core:payment_create"), {"sale": sale.pk})
        self.assertEqual(str(response.context["form"]["sale"].value()), str(sale.pk))
        self.assertNotIn("allow_overpayment", PaymentForm(user=self.manager).fields)
        self.assertIn("allow_overpayment", PaymentForm(user=self.admin).fields)
        self.assertEqual(self.client.get(reverse("core:payment_create"), {"sale": "invalid"}).status_code, 404)

    def test_changing_sale_land_releases_old_plot(self):
        sale = Sale.objects.first()
        old_land = sale.land
        new_land = Land.objects.filter(sale__isnull=True).first()
        sale.land = new_land
        sale.save()
        old_land.refresh_from_db()
        new_land.refresh_from_db()
        self.assertEqual(old_land.status, Land.STATUS_AVAILABLE)
        self.assertEqual(new_land.status, Land.STATUS_SOLD)

    def test_document_upload_download(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            payload = {"title": "Test agreement", "document_type": "AGREEMENT",
                       "customer": Customer.objects.first().pk,
                       "file": SimpleUploadedFile("agreement.txt", b"Test agreement", content_type="text/plain")}
            response = self.client.post(reverse("core:document_create"), payload)
            self.assertEqual(response.status_code, 302)
            document = Document.objects.get(title="Test agreement")
            response = self.client.get(reverse("core:document_download", args=[document.pk]))
            self.assertEqual(b"".join(response.streaming_content), b"Test agreement")
            response.close()
            self.client.post(reverse("core:document_delete", args=[document.pk]))
            self.assertFalse(Document.objects.filter(pk=document.pk).exists())

    # -- Payment register (writable table with search) ---------------------

    def register_payload(self, page_payments, extra_rows=(), delete=()):
        """Build a browser-like POST body for the payment register table."""
        data = {
            "row-TOTAL_FORMS": str(len(page_payments) + len(extra_rows)),
            "row-INITIAL_FORMS": str(len(page_payments)),
            "row-MIN_NUM_FORMS": "0",
            "row-MAX_NUM_FORMS": "1000",
        }
        for index, payment in enumerate(page_payments):
            data[f"row-{index}-id"] = str(payment.pk)
            data[f"row-{index}-sale"] = str(payment.sale_id)
            data[f"row-{index}-amount"] = str(payment.amount)
            data[f"row-{index}-payment_date"] = payment.payment_date.isoformat()
            data[f"row-{index}-payment_method"] = payment.payment_method
            if payment.pk in delete:
                data[f"row-{index}-DELETE"] = "on"
        for offset, row in enumerate(extra_rows):
            for key, value in row.items():
                data[f"row-{len(page_payments) + offset}-{key}"] = value
        return data

    def test_payment_register_is_writable(self):
        response = self.client.get(reverse("core:payment_register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="q"')                 # search box
        self.assertContains(response, 'name="row-TOTAL_FORMS"')   # writable grid
        self.assertContains(response, 'name="row-0-amount"')
        self.assertContains(response, 'name="row-0-id"')          # existing rows editable
        self.assertContains(response, "register-add-row")
        self.assertGreaterEqual(response.context["formset"].extra, 1)

    def test_payment_register_search_finds_a_person(self):
        payment = Payment.objects.select_related("sale__customer").first()
        name = payment.sale.customer.full_name
        response = self.client.get(reverse("core:payment_register"), {"q": name})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, name)
        self.assertGreaterEqual(response.context["total_shown"], 1)
        self.assertEqual(
            {row.sale.customer.full_name for row in response.context["page_obj"]},
            {name},
        )
        # A customer with no payments yet returns an empty, writable table.
        unpaid = (
            Customer.objects.filter(sales__payments__isnull=True)
            .distinct()
            .first()
        )
        response = self.client.get(
            reverse("core:payment_register"), {"q": unpaid.full_name}
        )
        self.assertEqual(response.context["total_shown"], 0)
        self.assertContains(response, "No payments match")
        self.assertContains(response, 'name="row-0-amount"')

    def test_payment_register_adds_and_edits_rows(self):
        response = self.client.get(reverse("core:payment_register"))
        rows = list(response.context["page_obj"].object_list)
        sale = next(
            s for s in Sale.objects.select_related("customer")
            if s.outstanding_balance >= Decimal("10.00")
        )
        payload = self.register_payload(rows, extra_rows=[{
            "sale": str(sale.pk), "amount": "10.00",
            "payment_date": "2026-09-10", "payment_method": "CASH",
        }])
        before = Payment.objects.count()
        response = self.client.post(reverse("core:payment_register"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.count(), before + 1)
        created = Payment.objects.get(payment_date="2026-09-10", sale=sale)
        self.assertEqual(created.amount, Decimal("10.00"))
        self.assertEqual(created.receipt_number[:4], "RCT-")

        # Now correct that row's amount in place.
        rows = list(self.client.get(reverse("core:payment_register")).context["page_obj"].object_list)
        index = rows.index(created)
        payload = self.register_payload(rows)
        payload[f"row-{index}-amount"] = "15.50"
        response = self.client.post(reverse("core:payment_register"), payload)
        self.assertEqual(response.status_code, 302)
        created.refresh_from_db()
        self.assertEqual(created.amount, Decimal("15.50"))

    def test_payment_register_blocks_overpayment_and_respects_delete_role(self):
        rows = list(self.client.get(reverse("core:payment_register")).context["page_obj"].object_list)
        fully_paid = next(s for s in Sale.objects.all() if s.outstanding_balance == Decimal("0.00"))
        payload = self.register_payload(rows, extra_rows=[{
            "sale": str(fully_paid.pk), "amount": "5.00",
            "payment_date": "2026-09-11", "payment_method": "CASH",
        }])
        response = self.client.post(reverse("core:payment_register"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exceeds the outstanding balance")
        self.assertFalse(Payment.objects.filter(payment_date="2026-09-11").exists())

        # Staff may not delete rows from the register.
        target = rows[0]
        self.client.force_login(self.staff)
        payload = self.register_payload(rows, delete={target.pk})
        response = self.client.post(reverse("core:payment_register"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(pk=target.pk).exists())

        # An administrator can.
        self.client.force_login(self.admin)
        payload = self.register_payload(rows, delete={target.pk})
        response = self.client.post(reverse("core:payment_register"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Payment.objects.filter(pk=target.pk).exists())

    # -- Records table (the single record-keeping screen) ------------------

    def records_payload(self, page_records, extra_rows=(), delete=()):
        """Build a browser-like POST body for the records table."""
        data = {
            "rec-TOTAL_FORMS": str(len(page_records) + len(extra_rows)),
            "rec-INITIAL_FORMS": str(len(page_records)),
            "rec-MIN_NUM_FORMS": "0",
            "rec-MAX_NUM_FORMS": "5000",
        }
        for index, record in enumerate(page_records):
            data[f"rec-{index}-id"] = str(record.pk)
            data[f"rec-{index}-record_date"] = record.record_date.isoformat()
            data[f"initial-rec-{index}-record_date"] = record.record_date.isoformat()
            data[f"rec-{index}-buyer_name"] = record.buyer_name
            data[f"rec-{index}-phone"] = record.phone
            data[f"rec-{index}-id_number"] = record.id_number
            data[f"rec-{index}-plot_number"] = record.plot_number
            data[f"rec-{index}-location"] = record.location
            data[f"rec-{index}-land_size"] = (
                "" if record.land_size is None else str(record.land_size)
            )
            data[f"rec-{index}-size_unit"] = record.size_unit
            data[f"rec-{index}-total_price"] = (
                "" if record.total_price is None else str(record.total_price)
            )
            data[f"rec-{index}-amount_paid"] = str(record.amount_paid)
            data[f"rec-{index}-payment_method"] = record.payment_method
            data[f"rec-{index}-notes"] = record.notes
            if record.pk in delete:
                data[f"rec-{index}-DELETE"] = "on"
        for offset, row in enumerate(extra_rows):
            # Date widgets submit this hidden initial value in a browser.
            data[f"initial-rec-{len(page_records) + offset}-record_date"] = (
                timezone.localdate().isoformat()
            )
            for key, value in row.items():
                data[f"rec-{len(page_records) + offset}-{key}"] = value
        return data

    def new_record_row(self, name, **overrides):
        row = {
            "record_date": "2026-09-15", "buyer_name": name, "phone": "0244000111",
            "id_number": "GHA-999999999-9", "plot_number": "77B",
            "location": "Oyibi", "land_size": "0.25", "size_unit": "ACRES",
            "total_price": "1000.00", "amount_paid": "400.00",
            "payment_method": "CASH", "notes": "Test row",
        }
        row.update(overrides)
        return row

    def test_records_is_the_landing_page_and_the_table_is_writable(self):
        self.assertRedirects(
            self.client.get(reverse("core:home")), reverse("core:records")
        )
        response = self.client.get(reverse("core:records"))
        self.assertEqual(response.status_code, 200)
        for needed in ['name="q"', 'name="rec-TOTAL_FORMS"', 'name="rec-0-record_date"',
                       'name="size"', "records-add-row", "records-add-rows",
                       "save-button", "save-guard", "✔ Save", "Buyer / customer",
                       "Total price", "Amount paid", "Balance", "Method of receipt",
                       "Receipt no."]:
            with self.subTest(part=needed):
                self.assertContains(response, needed)
        self.assertGreaterEqual(response.context["formset"].extra, 5)

    def test_records_accept_new_rows_and_extra_space(self):
        before = LandRecord.objects.count()
        # One row at a time, exactly as the "+ Add row" button produces it.
        payload = self.records_payload(
            [], extra_rows=[self.new_record_row("Mr. Test Buyer")]
        )
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 302)
        record = LandRecord.objects.get(buyer_name="Mr. Test Buyer")
        self.assertEqual(record.record_number[:4], "REC-")
        self.assertEqual(record.receipt_number[:4], "RCT-")
        self.assertEqual(record.balance, Decimal("600.00"))
        self.assertEqual(record.payment_status, LandRecord.STATUS_PART)
        self.assertEqual(LandRecord.objects.count(), before + 1)

        # More room than the blank rows already on the page.
        page_records = list(
            self.client.get(reverse("core:records"), {"size": 25})
            .context["page_obj"].object_list
        )
        extra = [self.new_record_row(f"Bulk Buyer {index}") for index in range(8)]
        payload = self.records_payload(page_records, extra_rows=extra)
        response = self.client.post(
            reverse("core:records") + "?size=25", payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandRecord.objects.count(), before + 9)

        # A bigger page holds more rows of the table.
        response = self.client.get(reverse("core:records"), {"size": 500})
        self.assertEqual(response.context["size"], 500)

    def test_records_search_edit_validation_and_delete_role(self):
        record = LandRecord.objects.create(
            buyer_name="Mrs. Search Me", phone="0209998877",
            plot_number="9C", location="Kasoa", total_price=Decimal("2000.00"),
            amount_paid=Decimal("500.00"),
        )
        response = self.client.get(reverse("core:records"), {"q": "Search Me"})
        self.assertEqual(response.context["total_records"], 1)
        self.assertContains(response, "Mrs. Search Me")
        response = self.client.get(reverse("core:records"), {"q": "Nobody Here"})
        self.assertEqual(response.context["total_records"], 0)
        self.assertContains(response, "No records match")

        # Correcting the money in the row works, and the balance follows.
        rows = list(
            self.client.get(reverse("core:records")).context["page_obj"].object_list
        )
        index = rows.index(record)
        payload = self.records_payload(rows)
        payload[f"rec-{index}-amount_paid"] = "2000.00"
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.balance, Decimal("0.00"))
        self.assertEqual(record.payment_status, LandRecord.STATUS_PAID)

        # Paying more than the price is refused.
        payload = self.records_payload(rows)
        payload[f"rec-{index}-amount_paid"] = "5000.00"
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be more than the total price")

        # Staff cannot delete a row from the table.
        self.client.force_login(self.staff)
        payload = self.records_payload(rows, delete={record.pk})
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LandRecord.objects.filter(pk=record.pk).exists())

        # An administrator can, and the receipt page renders.
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(
                reverse("core:record_receipt", args=[record.pk])
            ).status_code,
            200,
        )
        payload = self.records_payload(rows, delete={record.pk})
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LandRecord.objects.filter(pk=record.pk).exists())

    def test_create_admin_command_for_cloud_deploys(self):
        """The cloud admin command must be safe to re-run on every deploy."""
        out = StringIO()
        call_command("create_admin", "--username", "cloudadmin",
                     "--password", "StrongPass123!", stdout=out)
        user = User.objects.get(username="cloudadmin")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertTrue(user.is_staff)
        self.assertEqual(get_profile(user).role, UserProfile.ROLE_ADMIN)
        self.assertTrue(get_profile(user).can_delete)

        # Re-running without --force must not change the existing password.
        call_command("create_admin", "--username", "cloudadmin",
                     "--password", "AnotherPass456!", stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password("StrongPass123!"))

        # --force resets it.
        call_command("create_admin", "--username", "cloudadmin",
                     "--password", "AnotherPass456!", "--force", stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.check_password("AnotherPass456!"))

        # With no password given, one is generated and printed once.
        generated_out = StringIO()
        call_command("create_admin", "--username", "generatedadmin",
                     stdout=generated_out)
        self.assertIn("Generated password", generated_out.getvalue())
        self.assertTrue(User.objects.filter(username="generatedadmin").exists())

    def test_records_blank_extra_rows_do_not_block_the_save(self):
        """A browser submits the blank rows too; they must simply be ignored."""
        blank = {
            "record_date": timezone.localdate().isoformat(), "buyer_name": "",
            "phone": "", "id_number": "", "plot_number": "", "location": "",
            "land_size": "", "size_unit": "ACRES", "total_price": "",
            "amount_paid": "0.00", "payment_method": "CASH", "notes": "",
        }
        payload = self.records_payload(
            [], extra_rows=[self.new_record_row("Keep Me"), blank, blank, blank]
        )
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LandRecord.objects.count(), 1)
        self.assertEqual(LandRecord.objects.get().buyer_name, "Keep Me")

    def test_records_invalid_save_says_nothing_was_saved(self):
        """A rejected save must be obvious, and must not touch the database."""
        before = LandRecord.objects.count()
        row = self.new_record_row("")          # everything filled except the name
        payload = self.records_payload([], extra_rows=[row])
        response = self.client.post(reverse("core:records"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NOTHING WAS SAVED")
        self.assertContains(response, "Buyer / customer")
        self.assertEqual(LandRecord.objects.count(), before)

    def test_records_success_message_names_the_record_and_filter_warning(self):
        payload = self.records_payload(
            [], extra_rows=[self.new_record_row("Filter Note Buyer")]
        )
        response = self.client.post(
            reverse("core:records") + "?q=Filter+Note", payload, follow=True
        )
        content = response.content.decode()
        self.assertIn("Records saved", content)
        record = LandRecord.objects.get(buyer_name="Filter Note Buyer")
        self.assertIn(record.record_number, content)      # named in the message
        self.assertIn("search filter is active", content)  # explains hidden rows
        self.assertIn("save-button", content)              # one Save button
        # Searching that buyer does show the saved row.
        found = self.client.get(reverse("core:records"), {"q": "Filter Note"})
        self.assertEqual(found.context["total_records"], 1)

    def test_records_one_save_button_and_editable_after_saving(self):
        """There is a single Save button, and rows stay editable afterwards."""
        response = self.client.get(reverse("core:records"))
        self.assertContains(response, "save-button")
        self.assertNotContains(response, "Save changes")
        self.assertContains(response, "records-add-row")

        # First save: add a row.
        payload = self.records_payload(
            [], extra_rows=[self.new_record_row("Mr. Repeat Saver")]
        )
        self.assertEqual(
            self.client.post(reverse("core:records"), payload).status_code, 302
        )
        record = LandRecord.objects.get(buyer_name="Mr. Repeat Saver")
        self.assertEqual(record.amount_paid, Decimal("400.00"))
        self.assertEqual(record.balance, Decimal("600.00"))

        # Second save: change the money and notes of the row just saved.
        rows = list(
            self.client.get(reverse("core:records")).context["page_obj"].object_list
        )
        index = rows.index(record)
        payload = self.records_payload(rows)
        payload[f"rec-{index}-amount_paid"] = "1000.00"
        payload[f"rec-{index}-notes"] = "Paid in full at the office"
        self.assertEqual(
            self.client.post(reverse("core:records"), payload).status_code, 302
        )
        record.refresh_from_db()
        self.assertEqual(record.amount_paid, Decimal("1000.00"))
        self.assertEqual(record.notes, "Paid in full at the office")
        self.assertEqual(record.balance, Decimal("0.00"))
        self.assertEqual(record.payment_status, LandRecord.STATUS_PAID)

        # Third save: correct the same row again, so editing never stops working.
        rows = list(
            self.client.get(reverse("core:records")).context["page_obj"].object_list
        )
        index = rows.index(record)
        payload = self.records_payload(rows)
        payload[f"rec-{index}-amount_paid"] = "250.00"
        payload[f"rec-{index}-buyer_name"] = "Mr. Repeat Saver (corrected)"
        self.assertEqual(
            self.client.post(reverse("core:records"), payload).status_code, 302
        )
        record.refresh_from_db()
        self.assertEqual(record.buyer_name, "Mr. Repeat Saver (corrected)")
        self.assertEqual(record.amount_paid, Decimal("250.00"))
        self.assertEqual(record.balance, Decimal("750.00"))
        self.assertEqual(record.payment_status, LandRecord.STATUS_PART)
