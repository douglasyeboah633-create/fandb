"""Create or update a LandPro administrator without any prompts.

Cloud hosts usually give you no interactive terminal, so this command takes
everything from options or environment variables:

    python manage.py create_admin --username admin --password 'MyStrongPass1'
    DJANGO_ADMIN_PASSWORD='MyStrongPass1' python manage.py create_admin

If no password is given, a strong one is generated and printed once - sign in
and change it straight away.

Existing accounts are left alone unless --force is used to reset the password.
"""

import secrets
import string

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.models import UserProfile, get_profile


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Create (or update) an administrator account, using environment variables if given."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username", default=None,
            help="Username (default: DJANGO_ADMIN_USERNAME, else 'admin').",
        )
        parser.add_argument(
            "--password", default=None,
            help="Password (default: DJANGO_ADMIN_PASSWORD, else a generated one).",
        )
        parser.add_argument(
            "--email", default=None,
            help="Email address (default: DJANGO_ADMIN_EMAIL, else none).",
        )
        parser.add_argument(
            "--role", default="ADMIN",
            choices=[UserProfile.ROLE_ADMIN, UserProfile.ROLE_MANAGER,
                     UserProfile.ROLE_STAFF],
            help="LandPro role for the account (default: ADMIN).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Reset the password and role of an existing account.",
        )

    def handle(self, *args, **options):
        import os

        username = options["username"] or os.getenv("DJANGO_ADMIN_USERNAME") or "admin"
        password = (
            options["password"]
            or os.getenv("DJANGO_ADMIN_PASSWORD")
            or os.getenv("DJANGO_SUPERUSER_PASSWORD")
        )
        email = options["email"] or os.getenv("DJANGO_ADMIN_EMAIL") or ""
        role = options["role"]

        generated = False
        if not password:
            password = generate_password()
            generated = True

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "is_active": True},
        )
        if not created and not options["force"]:
            self.stdout.write(self.style.WARNING(
                f"Account '{username}' already exists - nothing changed "
                "(use --force to reset its password and role)."
            ))
            return

        if created:
            user.email = email
            user.is_active = True
        if created or options["force"]:
            user.set_password(password)

        # is_staff allows signing in to /django-admin/ for emergencies/backups.
        user.is_staff = True
        user.is_superuser = True
        user.save()

        profile = get_profile(user)
        profile.role = role
        profile.can_delete = True
        profile.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} the {role} account '{username}'."
        ))
        if generated:
            self.stdout.write(self.style.WARNING(
                f"Generated password (copy it now, change it after signing in): {password}"
            ))
        self.stdout.write(
            "Sign in at /login/ - the Records table opens automatically."
        )
