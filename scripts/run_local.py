"""One-command launcher for the LandPro Records Management System.

Prepares the environment on first run and starts the web server:

1. Creates ``.venv`` with Python 3.12+ when missing and installs
   ``requirements.txt`` into it.
2. Creates a private ``.env`` file with a generated secret key when one
   does not exist. An existing ``.env`` is never modified.
3. Applies database migrations.
4. Seeds demo records only when the database has no users and no
   customer/land records. Existing records are never deleted.
5. Starts the development server and opens the sign-in page.

Safe to run again at any time. From the project folder:

    python scripts\\run_local.py             # full launch
    python scripts\\run_local.py --check     # set up only, do not start
    python scripts\\run_local.py --port 8080 --no-browser
    python scripts\\run_local.py --no-seed   # never write demo records
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python"
)
REQUIREMENTS = ROOT / "requirements.txt"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
MIN_PYTHON = (3, 12)
DEFAULT_PORT = 8000

CHECK_COUNTS = """
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'landpro.settings')
django.setup()
from django.contrib.auth.models import User
from core.models import Customer, Land
print('COUNTS users=%d customers=%d lands=%d' % (
    User.objects.count(), Customer.objects.count(), Land.objects.count()))
"""


def info(message: str) -> None:
    print(f"[LandPro] {message}")


def fail(message: str) -> NoReturn:
    print(f"[LandPro] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(args: list[str]) -> subprocess.CompletedProcess:
    """Run a command inside the project folder, streaming its output."""
    return subprocess.run(args, cwd=str(ROOT))


# ---------------------------------------------------------------------
# Environment preparation
# ---------------------------------------------------------------------
def python_version(argv: list[str]) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [*argv, "-c", "import sys; print('%d %d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"(\d+)\s+(\d+)", result.stdout)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def find_system_python() -> list[str] | None:
    for argv in (["py", "-3"], ["py"], ["python"], ["python3"]):
        if shutil.which(argv[0]) is None:
            continue
        version = python_version(argv)
        if version and version >= MIN_PYTHON:
            return argv
    return None


def ensure_virtualenv() -> None:
    if VENV_PYTHON.exists():
        info(f"Using virtual environment: {VENV_DIR}")
        return
    if VENV_DIR.exists():
        info("Removing incomplete virtual environment ...")
        shutil.rmtree(VENV_DIR)
    python = find_system_python()
    if python is None:
        fail(
            "Python 3.12 or newer is required (Django 6.1 needs it). "
            "Install it from https://www.python.org/downloads/ and tick "
            "'Add python.exe to PATH' during setup, then start again."
        )
    info(f"Creating virtual environment with {' '.join(python)} ...")
    if run([*python, "-m", "venv", str(VENV_DIR)]).returncode != 0:
        fail("Could not create the virtual environment; see messages above.")
    if not VENV_PYTHON.exists():
        fail("Virtual environment was created but its interpreter is missing.")
    info("Virtual environment created.")


def dependencies_ok() -> bool:
    probe = (
        "import django, whitenoise, dj_database_url, dotenv, "
        "reportlab, openpyxl"
    )
    return subprocess.run(
        [str(VENV_PYTHON), "-c", probe], cwd=str(ROOT), capture_output=True,
    ).returncode == 0


def ensure_dependencies() -> None:
    if dependencies_ok():
        info("Dependencies are installed.")
        return
    info("Installing Python dependencies (first run only) ...")
    if run([
        str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS),
    ]).returncode != 0:
        fail("Dependency installation failed; see messages above.")
    if not dependencies_ok():
        fail("Dependencies were installed but could not be imported.")
    info("Dependencies installed.")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        info("Using existing .env file.")
        return
    template = ""
    if ENV_EXAMPLE.exists():
        template = ENV_EXAMPLE.read_text(encoding="utf-8")
    kept = [
        line for line in template.splitlines()
        if not line.strip().startswith("DJANGO_SECRET_KEY")
    ]
    secret = "django-insecure-" + secrets.token_urlsafe(64)
    kept.append(f"DJANGO_SECRET_KEY={secret}")
    ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    info(f"Created {ENV_FILE} with a generated secret key (keep it private).")


def manage(args: list[str]) -> int:
    return run([str(VENV_PYTHON), "manage.py", *args]).returncode


# ---------------------------------------------------------------------
# Database preparation
# ---------------------------------------------------------------------
def apply_migrations() -> None:
    info("Applying database migrations ...")
    if manage(["migrate"]) != 0:
        fail("Migrations failed; see messages above.")
    info("Database is up to date.")


def record_counts() -> dict[str, int]:
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", CHECK_COUNTS],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        fail("Could not read the database; see messages above.")
    match = re.search(
        r"COUNTS users=(\d+) customers=(\d+) lands=(\d+)", result.stdout,
    )
    if not match:
        fail("Unexpected database check output; see messages above.")
    return {
        "users": int(match.group(1)),
        "customers": int(match.group(2)),
        "lands": int(match.group(3)),
    }


def seed_if_needed(counts: dict[str, int], args: argparse.Namespace) -> None:
    if args.no_seed:
        info("Skipping demo data (--no-seed).")
        return
    empty_business = counts["customers"] == 0 and counts["lands"] == 0
    if not args.seed and counts["users"] > 0 and not empty_business:
        info(
            "Database already has records; demo seeding skipped and "
            "existing data is protected. Use --seed to force a refresh."
        )
        return
    if args.seed and counts["users"] > 0:
        info("Forcing seed: business settings and demo roles will be reset.")
    info("Preparing starter records ...")
    if manage(["seed_data"]) != 0:
        fail("Seeding failed; see messages above.")


# ---------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------
def pick_port(preferred: int) -> int:
    for port in (preferred, 8080, 8888, 8090):
        probe = socket.socket()
        try:
            busy = probe.connect_ex(("127.0.0.1", port)) == 0
        finally:
            probe.close()
        if not busy:
            return port
    fail("No free local port was found; close other applications and retry.")


def start_server(port: int, open_browser: bool) -> int:
    actual = pick_port(port)
    if actual != port:
        info(f"Port {port} is busy; using {actual} instead.")
    url = f"http://127.0.0.1:{actual}/"
    info(f"Starting LandPro on {url}  (press Ctrl+C to stop)")
    process = subprocess.Popen(
        [
            str(VENV_PYTHON), "manage.py", "runserver",
            f"127.0.0.1:{actual}", "--noreload",
        ],
        cwd=str(ROOT),
    )
    exit_code = 0
    try:
        deadline = time.time() + 45
        while time.time() < deadline:
            if process.poll() is not None:
                fail("The server exited unexpectedly; see messages above.")
            try:
                with urllib.request.urlopen(url + "login/", timeout=2):
                    break
            except urllib.error.HTTPError:
                break  # the server responded, so it is ready
            except OSError:
                time.sleep(0.25)
        else:
            fail("The server did not become ready in time; see above.")
        info("LandPro is running. Open " + url + " in your browser.")
        info(
            "Demo sign-in: admin / Admin@12345  |  manager / Admin@12345"
            "  |  staff / Staff@12345"
        )
        if open_browser:
            webbrowser.open(url)
        process.wait()
    except KeyboardInterrupt:
        info("Stopping ...")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    info("Server stopped.")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and start the LandPro web application.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"preferred local port (default {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="do not open the browser automatically",
    )
    parser.add_argument(
        "--no-server", "--check", dest="no_server", action="store_true",
        help="prepare everything but do not start the server",
    )
    parser.add_argument(
        "--no-seed", action="store_true",
        help="never create demo records",
    )
    parser.add_argument(
        "--seed", action="store_true",
        help="force the demo seed even when records already exist",
    )
    args = parser.parse_args()

    print("LandPro Records Management System - one-step launcher")
    print(f"Project folder: {ROOT}")
    ensure_virtualenv()
    ensure_dependencies()
    ensure_env_file()
    apply_migrations()
    seed_if_needed(record_counts(), args)
    if args.no_server:
        info("Setup complete. Start the site with .\\start-landpro.bat")
        return 0
    return start_server(args.port, not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
