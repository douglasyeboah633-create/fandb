# Deploying ABI LAND (and fixing the `404 NOT_FOUND`)

> **You must redeploy after pulling this fix.** Vercel only picks up code
> changes on a new deployment — go to **Deployments → … → Redeploy**, or
> push a new commit. The old deployment will keep 404ing until you do.

## The error you saw

```
404 NOT_FOUND
cpt1::m27rm-1789919925060-64d1b2a5f04a
```

That footer — a code like `cpt1::...` — is the signature of **Vercel's edge
network**, not Django. It means the request never reached your application:
Vercel served the 404 itself because it did not recognise the project as a
Django app. The usual causes, in order:

1. **Root Directory is wrong** — Vercel must find `manage.py` at the project
   root. If you pushed a parent folder (e.g. the whole Desktop) or a
   subfolder, detection never triggers.
2. **Framework Preset is wrong** — it must detect Django (Python). If the
   project page says "Other" or shows a static-site build in the logs,
   Django detection did not happen.
   (Fixed in this project: `landpro/settings.py` now sets **only**
   `WSGI_APPLICATION` — when both WSGI and ASGI are set, Vercel prefers
   ASGI, which 404s this WSGI project.)
3. **A stray `vercel.json`** with `builds`/`routes` overrides zero-config
   Django routing (this project intentionally ships **no** `vercel.json`).
4. **An `api/` folder** at the repo root makes Vercel treat the project as
   plain Python serverless functions instead of a Django app (there is
   none in this project on purpose).

**Proof the application itself is healthy** — production mode
(`DEBUG=False`) with a proper host allow-list, exactly how a host runs it,
checked locally:

```
DEBUG: False
static backend: CompressedManifestStaticFilesStorage
login page: 200 | has form: True
/records/ signed out -> 302 (redirect to login, NOT 404)
unknown url -> 404 (Django's friendly error page, NOT Vercel's edge 404)
```

## Fix checklist — Vercel project settings (do this first)

These live in the Vercel dashboard under **Project → Settings → General**
(Root Directory, Framework Preset) and **Deployments → Build Logs**:

- [ ] **Root Directory** is the folder containing `manage.py`. If your repo
      root holds `manage.py`, `landpro/`, `core/`, `requirements.txt` —
      leave Root Directory empty (or `.`). If you pushed a parent folder,
      set Root Directory to the `land` folder.
- [ ] **Framework Preset** shows **Django (Python)**. Vercel may set the
      preset to "Other" (Framework: Other / Root: `./`) — that is the
      deployment-smell behind your exact 404 footer: Django detection did
      not trigger, so no URL ever reaches the app. DEPLOY.md had you leave
      this on auto-detect and that produced 404 for you. Fix: set the
      preset to **Django** explicitly, redeploy, and confirm the Build Logs
      show the Django/Python build — not a static-site build — before
      changing code.
- [ ] **Build & Development Settings are untouched**: no custom Build
      Command, Output Directory, or Install Command for a Django project.
      Vercel installs `requirements.txt` and runs `collectstatic` for you.
      Run `migrate` + `create_admin` separately (see the database section
      below) — a cold `/tmp` database will not keep records otherwise.
- [ ] **Build Logs** of the failed deployment show Python/Django being
      detected. A static-site build log means Root Directory is wrong.
- [ ] **Environment variables** are set (Project → Settings →
      Environment Variables): at minimum `DJANGO_SECRET_KEY` (long random
      string), `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` (your exact
      deployment domain, e.g. `abiland-xyz.vercel.app`), and
      `DJANGO_CSRF_TRUSTED_ORIGINS` (the same domain with `https://` in
      front, e.g. `https://abiland-xyz.vercel.app` — CSRF origins take no
      wildcards, so the app cannot guess this for you). The app
      auto-accepts `*.vercel.app` hosts for *serving* pages when it sees
      `VERCEL=1`, but signing in needs those two exact values.

Then **redeploy** (Deployments → … → Redeploy, or push a new commit).
A green Django build where `/login/` renders the sign-in page means the
404 is fixed.

## If the 404 persists after the checklist

1. Confirm what you pushed: the repo root must contain `manage.py`,
   `requirements.txt`, `landpro/` and `core/` — not a wrapper folder.
   Open the repo on GitHub and check the file list.
2. Open the failed deployment's **Build Logs** and look for the line where
   Vercel detects the framework. Copy it to me along with your
   Root Directory and Framework Preset values and I will pinpoint it.
3. Note that `Procfile`, `runtime.txt` and `build.sh` in this project are
   for Render/Railway/VPS hosts — **Vercel ignores them**, so they can
   neither cause nor fix a Vercel 404.

```bash
cd "C:\Users\MacBook Pro\Desktop\land"
git init
git add .
git commit -m "ABI LAND records application"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

**2. Create the Vercel project from that repo**

- Import the repo in Vercel. When it asks for the settings, apply the
  **Fix checklist** above: Root Directory = folder with `manage.py`,
  Framework Preset = Django (or auto), no custom build command.
- Add the environment variables (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`).
- Deploy, then open `/login/`. If it 404s, read the Build Logs before
  changing anything else — they say whether Django was detected.

## After the 404 is fixed — the database question

Vercel's filesystem is read-only outside `/tmp` and is rebuilt on every
deploy, so the app boots with SQLite under `/tmp` when no `DATABASE_URL`
is set (see `landpro/settings.py`). That is only enough to prove the 404
is gone: **records saved there vanish on the next deploy, and the empty
cold database has no administrator account** (seed/demo accounts live only
in your local `db.sqlite3`). For a records system, before entering live
data:

- **Neon / Supabase / any managed PostgreSQL** — create a database, copy
  its connection URL into Vercel as `DATABASE_URL`, redeploy. The app
  picks it up automatically via `dj-database-url`.
- Apply migrations to it (`python manage.py migrate` against that
  `DATABASE_URL`) and create your administrator
  (`python manage.py create_admin` — set `DJANGO_ADMIN_USERNAME` /
  `DJANGO_ADMIN_PASSWORD`, or let it print a generated one).
- Uploaded documents need external file storage (S3/Cloudinary) on
  serverless hosts — local `media/` does not persist there either.

## Other hosts (Render, Railway, VPS)

**2. Create the web service (Render example)**

| Setting | Value |
|---|---|
| Language | Python |
| Build command | `./build.sh` |
| Start command | `gunicorn landpro.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |

`build.sh` installs `requirements.txt`, runs `collectstatic` (WhiteNoise serves
those files) and applies migrations.

**3. Create the database**

Render → **New → PostgreSQL** → copy the **Internal Database URL**. A SQLite
file cannot be used where the disk is rebuilt on every deploy — your records
would vanish.

**4. Add the environment variables** (Render → service → Environment)

| Name | Value | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | long random string | Generate a fresh one; never reuse the local one |
| `DJANGO_DEBUG` | `False` | Must be `False` on the Internet |
| `DJANGO_ALLOWED_HOSTS` | `your-app.onrender.com` | Your real domain; comma-separate several |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://your-app.onrender.com` | Without this, signing in fails |
| `DATABASE_URL` | the PostgreSQL URL | From step 3 |
| `DJANGO_ADMIN_USERNAME` | `admin` | Optional, for the first account |
| `DJANGO_ADMIN_PASSWORD` | a strong password | Optional, for the first account |

**5. Deploy**, watch the **Logs**, then create your administrator once in
Render's **Shell** tab:

```bash
python manage.py create_admin
```

It reads `DJANGO_ADMIN_USERNAME` / `DJANGO_ADMIN_PASSWORD`; with no password it
generates a strong one and prints it once. (Or uncomment the last line of
`build.sh` to create it automatically on each deploy.)

**6. Open `https://your-app.onrender.com/login/`** — Records opens after
signing in. On the free tier the service sleeps when idle, so the first visit
takes a few seconds; your data stays safe in PostgreSQL.

## Option B — Other hosts, briefly

- **Railway** — connect the repo, add the PostgreSQL plugin, set the same
  variables; the `Procfile` supplies the start command.
- **Fly.io** — `fly launch` (accept the generated Dockerfile), add a volume for
  SQLite and `media/` if you prefer SQLite, then `fly secrets set` the variables.
- **PythonAnywhere** — upload the code, create a virtualenv, add a web app using
  the manual WSGI configuration for `landpro.wsgi:application`, and set the
  variables inside the WSGI file.
- **VPS** — `gunicorn` behind nginx, supervised by systemd; keep `db.sqlite3` and
  `media/` on the server disk and back them up.

## Environment variables reference

| Variable | Example | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | `k9f…` (50+ characters) | Session/CSRF signing. Keep private |
| `DJANGO_DEBUG` | `False` | Never `True` on a public site |
| `DJANGO_ALLOWED_HOSTS` | `abiland.example.com,www.abiland.example.com` | Accepted host names |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://abiland.example.com` | Needed for signing in over HTTPS |
| `DATABASE_URL` | `postgres://user:pass@host:5432/db` | PostgreSQL; omit to use SQLite |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` | Forces HTTPS (already the default when DEBUG is off) |
| `DJANGO_TIME_ZONE` | `Africa/Accra` | Local dates and times |
| `BUSINESS_NAME`, `BUSINESS_PHONE`, `BUSINESS_EMAIL`, `BUSINESS_ADDRESS`, `CURRENCY_SYMBOL` | `ABI LAND…`, `+233…`, `GHS` | Shown on the site and receipts (also editable under Settings) |
| `DJANGO_ADMIN_USERNAME` / `DJANGO_ADMIN_PASSWORD` | `admin` / strong password | Used by `python manage.py create_admin` |

## Your local records do not travel with the code

`db.sqlite3` stays on your PC (and is ignored by Git), so a freshly deployed
site starts with an **empty** database. To carry your records across:

1. Locally, open **Settings → Backup** and download the JSON/CSV exports (and
   copy `media/`), then
2. on the deployed site, sign in and type them in again — or tell me and I will
   add an **import** command so the exported file can be loaded on the server.

## After deploying — checklist

- [ ] `https://your-domain/login/` shows the sign-in page (no 404)
- [ ] Sign in, open **Records**, type a row, click **Save**, reload the page —
      the row is still there
- [ ] **Activity Log** lists your save
- [ ] Colours and layout look right (static files loading)
- [ ] `http://` redirects to `https://`, and the padlock appears
- [ ] Change the generated administrator password
- [ ] Backups arranged: **Settings → Backup**, plus your host's PostgreSQL backups
- [ ] `python manage.py check --deploy` reports no errors

## Security reminders

- Never commit `.env`, `db.sqlite3` or `media/` to a public repository.
- Rotate `DJANGO_SECRET_KEY` if it was ever exposed; a leaked key lets someone
  forge sessions.
- Keep `DJANGO_DEBUG=False` in production or stack traces leak to visitors.
- `DJANGO_ALLOWED_HOSTS` must list the real domain, and
  `DJANGO_CSRF_TRUSTED_ORIGINS` must include `https://your-domain`, otherwise
  signing in fails.
- Treat the PostgreSQL URL and credentials as secrets.

