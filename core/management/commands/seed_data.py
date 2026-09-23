"""Seed the database with demo records so the system can be tested immediately.

Usage:
    python manage.py seed_data
    python manage.py seed_data --fresh      # removes demo records first
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Customer,
    Land,
    Payment,
    Sale,
    Setting,
    UserProfile,
    get_profile,
)


class Command(BaseCommand):
    help = "Create demo users, settings, customers, lands, sales and payments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh", action="store_true",
            help="Delete existing customers, lands, sales and payments first.",
        )
        parser.add_argument("--admin-password", default="Admin@12345")
        parser.add_argument("--staff-password", default="Staff@12345")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        if options["fresh"]:
            Payment.objects.all().delete()
            Sale.objects.all().delete()
            Land.objects.all().delete()
            Customer.objects.all().delete()
            self.stdout.write(self.style.WARNING("Existing records deleted."))

        self.create_users(options["admin_password"], options["staff_password"])
        self.create_settings()

        customers = self.create_customers()
        lands = self.create_lands()
        self.create_sales_and_payments(customers, lands)

        self.stdout.write(self.style.SUCCESS("\nDemo data created successfully."))
        self.stdout.write(
            "Sign in with:  admin / "
            f"{options['admin_password']}   (administrator)\n"
            "               manager / "
            f"{options['admin_password']}   (manager)\n"
            "               staff / "
            f"{options['staff_password']}   (staff)\n"
        )

    # ------------------------------------------------------------------
    def create_users(self, admin_password, staff_password):
        users = [
            ("admin", "System", "Administrator", "admin@landpro.local",
             UserProfile.ROLE_ADMIN, True, True, admin_password),
            ("manager", "Grace", "Mensah", "manager@landpro.local",
             UserProfile.ROLE_MANAGER, True, True, admin_password),
            ("staff", "Kwame", "Boateng", "staff@landpro.local",
             UserProfile.ROLE_STAFF, True, False, staff_password),
        ]
        for username, first, last, email, role, is_active, can_delete, password in users:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first, "last_name": last, "email": email,
                    "is_active": is_active,
                },
            )
            if created:
                user.set_password(password)
                user.save()
            profile = get_profile(user)
            profile.role = role
            profile.can_delete = can_delete
            profile.phone = "+233200000000"
            profile.save()
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action} user: {username} ({role})")

    # ------------------------------------------------------------------
    def create_settings(self):
        Setting.set("business_name", "ABI LAND")
        Setting.set("business_phone", "+233 24 000 0000")
        Setting.set("business_email", "info@landpro.example")
        Setting.set("business_address", "12 Independence Avenue, Accra, Ghana")
        Setting.set("currency_symbol", "GHS")
        Setting.set("allow_overpayment", "False")
        self.stdout.write("  Business settings configured.")

    # ------------------------------------------------------------------
    def create_customers(self):
        rows = [
            ("Mr. Kofi Anane", "GHA-123456789-0", "0244123456", "0201234567",
             "kofi.anane@example.com", "Adenta Housing Down, Accra",
             "Businessman", "Akosua Anane", "0245556677"),
            ("Mrs. Ama Serwaa", "GHA-234567890-1", "0202345678", "0554321098",
             "ama.serwaa@example.com", "Kasoa Ofaakor, Central Region",
             "Trader", "Yaw Serwaa", "0209876543"),
            ("Mr. Daniel Osei", "GHA-345678901-2", "0553456789", "0243987654",
             "daniel.osei@example.com", "Tema Community 25",
             "Engineer", "Esi Osei", "0551122334"),
            ("Ms. Abena Frimpong", "GHA-456789012-3", "0244567890", "",
             "abena.frimpong@example.com", "Kumasi Asokwa",
             "Teacher", "Kojo Frimpong", "0244560000"),
            ("Chief Nana Adjei", "GHA-567890123-4", "0205678901", "0591234567",
             "nana.adjei@example.com", "Ningo Prampram, Greater Accra",
             "Chief / Farmer", "Naa Adjei", "0205678000"),
        ]
        customers = []
        for (name, card, phone, alt, email, address, occupation,
             kin, kin_phone) in rows:
            customer, created = Customer.objects.get_or_create(
                ghana_card=card,
                defaults={
                    "full_name": name, "phone": phone, "alt_phone": alt,
                    "email": email, "address": address,
                    "occupation": occupation, "next_of_kin": kin,
                    "next_of_kin_phone": kin_phone,
                    "date_registered": timezone.localdate() - timedelta(days=90),
                },
            )
            customers.append(customer)
            if created:
                self.stdout.write(f"  Customer: {customer.full_name}")
        return customers

    # ------------------------------------------------------------------
    def create_lands(self):
        rows = [
            ("12", "A", "Adenta Municipality", "Greater Accra", "Adenta",
             "Adenta Housing Down", Decimal("0.25"), "ACRES", "RESIDENTIAL",
             Decimal("85000.00"), "AVAILABLE", "6.6989, -0.1536"),
            ("13", "A", "Adenta Municipality", "Greater Accra", "Adenta",
             "Adenta Housing Down", Decimal("0.25"), "ACRES", "RESIDENTIAL",
             Decimal("88000.00"), "AVAILABLE", "6.6992, -0.1531"),
            ("7", "B", "Kasoa", "Central Region", "Awutu Senya East",
             "Ofaakor", Decimal("0.30"), "ACRES", "RESIDENTIAL",
             Decimal("65000.00"), "AVAILABLE", "5.5333, -0.4167"),
            ("21", "C", "Tema Community 25", "Greater Accra", "Tema",
             "Community 25", Decimal("0.20"), "ACRES", "COMMERCIAL",
             Decimal("150000.00"), "AVAILABLE", "5.6698, 0.0166"),
            ("5", "D", "Ningo Prampram", "Greater Accra", "Ningo Prampram",
             "Old Ningo", Decimal("2.00"), "ACRES", "AGRICULTURAL",
             Decimal("120000.00"), "AVAILABLE", "5.7500, 0.1167"),
            ("9", "B", "Kasoa", "Central Region", "Awutu Senya East",
             "Ofaakor", Decimal("0.30"), "ACRES", "RESIDENTIAL",
             Decimal("70000.00"), "RESERVED", "5.5340, -0.4170"),
            ("33", "E", "Kumasi Asokwa", "Ashanti Region", "Kumasi Metro",
             "Asokwa", Decimal("0.15"), "ACRES", "RESIDENTIAL",
             Decimal("95000.00"), "AVAILABLE", "6.6666, -1.6167"),
            ("41", "E", "Kumasi Asokwa", "Ashanti Region", "Kumasi Metro",
             "Asokwa", Decimal("0.15"), "ACRES", "COMMERCIAL",
             Decimal("130000.00"), "AVAILABLE", "6.6670, -1.6160"),
            ("2", "F", "Dodowa", "Greater Accra", "Shai Osudoku",
             "Dodowa Township", Decimal("0.50"), "ACRES", "MIXED",
             Decimal("78000.00"), "AVAILABLE", "5.8833, 0.0833"),
            ("18", "G", "Oyibi", "Greater Accra", "Kpone Katamanso",
             "Oyibi", Decimal("0.25"), "ACRES", "RESIDENTIAL",
             Decimal("72000.00"), "AVAILABLE", "5.8167, 0.0833"),
        ]
        lands = []
        for (plot, block, location, region, district, community, size,
             unit, land_type, price, status, gps) in rows:
            land, created = Land.objects.get_or_create(
                plot_number=plot, block_number=block,
                defaults={
                    "location": location, "region": region,
                    "district": district, "community": community,
                    "land_size": size, "size_unit": unit,
                    "land_type": land_type, "price": price, "status": status,
                    "gps_coordinates": gps,
                    "description": (
                        f"Plot {plot}, Block {block} located at {location}. "
                        "Fully serviced with access roads."
                    ),
                    "date_added": timezone.localdate() - timedelta(days=60),
                },
            )
            lands.append(land)
            if created:
                self.stdout.write(
                    f"  Land: {land.land_id} - Plot {land.plot_number} ({status})"
                )
        return lands


    def create_sales_and_payments(self, customers, lands):
        from core.models import AuditLog
        agent = User.objects.get(username="staff")
        today = timezone.localdate()
        for index, land_index in enumerate([0, 2, 3, 6, 4]):
            land = lands[land_index]
            sale, created = Sale.objects.get_or_create(
                land=land,
                defaults={"customer": customers[index], "selling_price": land.price,
                          "sale_date": today - timedelta(days=25 - index * 4),
                          "sales_agent": agent, "payment_method": "CASH",
                          "notes": "Demonstration transaction — not a real sale."},
            )
            if not created:
                continue
            AuditLog.log(agent, AuditLog.ACTION_CREATE, sale, "Created demo sale.")
            fractions = [Decimal("0.5"), Decimal("0.5")] if index == 0 else (
                [Decimal("0.3")] if index in (1, 2, 4) else []
            )
            for offset, fraction in enumerate(fractions):
                payment = Payment.objects.create(
                    sale=sale, amount=(land.price * fraction).quantize(Decimal("0.01")),
                    payment_date=sale.sale_date + timedelta(days=offset),
                    payment_method="CASH", recorded_by=agent, notes="Demo payment",
                )
                AuditLog.log(agent, AuditLog.ACTION_CREATE, payment, "Created demo payment.")
            self.stdout.write(f"  Sale: {sale.transaction_id}")
