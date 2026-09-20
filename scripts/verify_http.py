"""Start a temporary local server, verify HTTP assets, then stop it.
Run with the project virtualenv Python. Does not change business records.
"""
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def main():
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "manage.py"), "runserver", "127.0.0.1:8001", "--noreload"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError("Temporary server exited; check that port 8001 is free.")
            try:
                with urlopen("http://127.0.0.1:8001/login/", timeout=1) as response:
                    assert response.status == 200
                    assert b"csrfmiddlewaretoken" in response.read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Temporary server did not become ready.")
        print("Live login HTTP 200; CSRF form present")
        for path in ["/static/css/app.css", "/static/css/responsive.css",
                     "/static/js/dashboard.js", "/static/vendor/chart.umd.js"]:
            with urlopen("http://127.0.0.1:8001" + path, timeout=3) as response:
                body = response.read()
                assert response.status == 200 and body
                print(path, response.status, len(body), "bytes")
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
