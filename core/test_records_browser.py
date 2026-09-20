"""Exercise the Records page with the controls actually rendered to a browser."""
from html.parser import HTMLParser
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AuditLog, LandRecord


class RecordsControls(HTMLParser):
    """Serialize the Records form, including Django's hidden initial values."""

    def __init__(self, html):
        super().__init__()
        self.data = {}
        self.active = False
        self.select = None
        self.textarea = None
        self.in_template = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "template":
            self.in_template = True
        if self.in_template:
            return
        if tag == "form":
            self.active = "save-guard" in attrs.get("class", "").split()
        if not self.active:
            return
        name = attrs.get("name")
        if tag == "input" and name and "disabled" not in attrs:
            if attrs.get("type") in ("checkbox", "radio") and "checked" not in attrs:
                return
            self.data[name] = attrs.get("value", "")
        if tag == "select":
            self.select = name
        if tag == "option" and self.select:
            if self.select not in self.data or "selected" in attrs:
                self.data[self.select] = attrs.get("value", "")
        if tag == "textarea" and name:
            self.textarea = name
            self.data[name] = ""

    def handle_endtag(self, tag):
        if tag == "template":
            self.in_template = False
        if tag == "form":
            self.active = False
        if tag == "select":
            self.select = None
        if tag == "textarea":
            self.textarea = None

    def handle_data(self, data):
        if self.active and self.textarea and not self.in_template:
            self.data[self.textarea] += data


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class RecordsBrowserPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_data", stdout=StringIO())
        cls.admin = User.objects.get(username="admin")

    def test_fill_one_row_save_reload_edit_and_preserve_audit(self):
        self.client.force_login(self.admin)
        url = reverse("core:records")
        page = self.client.get(url)
        data = RecordsControls(page.content.decode()).data
        self.assertEqual(data["rec-TOTAL_FORMS"], "5")
        data.update({
            "rec-0-buyer_name": "Persistence test buyer",
            "rec-0-total_price": "1000.00",
            "rec-0-amount_paid": "400.00",
            "rec-0-notes": "Keep this entry after reloading",
        })
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "Records saved")
        self.assertEqual(LandRecord.objects.count(), 1)
        record = LandRecord.objects.get()
        audit = AuditLog.objects.get(
            model_name="LandRecord", object_id=str(record.pk),
            action=AuditLog.ACTION_CREATE,
        )
        self.assertIn(record.buyer_name, audit.description)
        reloaded = self.client.get(url)
        self.assertContains(reloaded, record.buyer_name)
        data = RecordsControls(reloaded.content.decode()).data
        data.update({"rec-0-amount_paid": "500.00", "rec-0-notes": "Corrected"})
        response = self.client.post(url, data, follow=True)
        self.assertContains(response, "Records saved")
        record.refresh_from_db()
        self.assertEqual(str(record.amount_paid), "500.00")
        self.assertEqual(record.notes, "Corrected")
        self.assertEqual(LandRecord.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(pk=audit.pk).exists())
        self.assertTrue(AuditLog.objects.filter(
            model_name="LandRecord", object_id=str(record.pk),
            action=AuditLog.ACTION_UPDATE,
        ).exists())
        self.assertFalse(AuditLog.objects.filter(
            model_name="LandRecord", action=AuditLog.ACTION_DELETE,
        ).exists())
        activity = self.client.get(reverse("core:audit_list"), {
            "q": record.record_number,
        })
        self.assertContains(activity, audit.description)
        self.assertContains(activity, "Updated record")
        self.assertContains(activity, record.record_number)
