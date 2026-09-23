# ABI LAND Records Management System

Project: `C:\Users\MacBook Pro\Desktop\land`

Django, Bootstrap 5, Chart.js, SQLite, ReportLab, openpyxl and WhiteNoise. Assets are local; normal use needs no CDN. The installed environment uses Python 3.12.10 and Django 6.1.1 (as pinned in requirements), not Django 5.x from the initial summary. This is a functional local application, **not a certified production deployment**. Review the release limitations below before storing live financial or identity records.

## 1. Install

In PowerShell:

```powershell
Set-Location 'C:\Users\MacBook Pro\Desktop\land'
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
Copy-Item '.env.example' '.env'
& '.\.venv\Scripts\python.exe' -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Do not recreate the existing environment unnecessarily or overwrite an existing `.env`. Put a newly generated secret into `DJANGO_SECRET_KEY` in `.env`. Never commit secrets. All following commands run from the project directory above.

## 2. Configure the database

Leave `DATABASE_URL` empty for local SQLite at `C:\Users\MacBook Pro\Desktop\land\db.sqlite3`. Configure branding in Settings. For PostgreSQL, install a supported psycopg driver and set `DATABASE_URL` to your private database URL; PostgreSQL is not validated by the SQLite test run. Do not expose the database directly to the Internet.

## 3. Apply migrations

```powershell
& '.\.venv\Scripts\python.exe' manage.py migrate
& '.\.venv\Scripts\python.exe' manage.py check
```

Existing migrations are included. Use `makemigrations` only after intentionally changing models.

## 4. Create an administrator

For a clean database:

```powershell
& '.\.venv\Scripts\python.exe' manage.py createsuperuser
& '.\.venv\Scripts\python.exe' manage.py shell -c "from django.contrib.auth.models import User; from core.models import get_profile; u=User.objects.filter(is_superuser=True).earliest('id'); p=get_profile(u); p.role='ADMIN'; p.save(); print('ABI LAND administrator:',u.username)"
```

The application role is separate from Django's `is_staff`/`is_superuser` flags. ABI LAND Users manages application roles; `/django-admin/` requires Django admin permissions.

For **disposable demo databases only**:

```powershell
& '.\.venv\Scripts\python.exe' manage.py seed_data
```

Default demo credentials: `admin / Admin@12345`, `manager / Admin@12345`, `staff / Staff@12345`. Existing demo users retain their passwords when seeding again. Change or remove demo accounts before any real use. Seeding resets business settings and updates demo roles. **`seed_data --fresh` deletes all customers, lands, sales and payments, not just demo records. Never run it against live data.**

## 5. Start locally (one step)

Easiest: double-click **`start-landpro.bat`** in `C:\Users\MacBook Pro\Desktop\land`, or run `python scripts\run_local.py` in a terminal. The launcher prepares everything automatically — virtual environment, dependencies, a private `.env` with a generated secret key, migrations and starter records — then starts the site and opens http://127.0.0.1:8000/ in your browser. It never deletes existing records; it only seeds when the database is empty. Options: `--seed` (refresh demo data), `--no-seed` (never seed), `--check` (prepare without starting), `--port 8080`, `--no-browser`.

Manual alternative:

```powershell
& '.\.venv\Scripts\python.exe' manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000/ and sign in. Keep `DJANGO_DEBUG=True` only for local development. Stop with Ctrl+C. Do not expose `runserver` publicly.

## 5.1 Records — the one table you work in

Signing in opens **Records** at http://127.0.0.1:8000/records/ (the only workspace item in the sidebar). Everything you keep is typed straight into this one table; there are no other forms to fill in first.

**The columns** (one row = one record):

| Column | What to type |
|---|---|
| **No.** | Automatic record number (REC-00001). Click it to open the printable receipt. |
| **Date** | Date of the record (today by default). |
| **Buyer / customer** | Name of the person buying. Required — a row with no name is ignored. |
| **Phone** | Contact number. |
| **Ghana card / ID** | ID number for verification. |
| **Plot no.** | Plot identifier, e.g. 12A. |
| **Location / community** | Town or community of the plot. |
| **Size** and **Unit** | Plot size, with its unit (Acres, Plots, Hectares, Square metres, Feet). |
| **Total price** | Agreed price for the plot. |
| **Amount paid** | Money received so far. |
| **Balance** | Calculated for you: total price − amount paid, with a Fully paid / Part paid / Not paid badge. Updates as you type. |
| **Method of receipt** | Cash, Mobile Money, Bank transfer, Cheque or Other. |
| **Receipt no.** | Automatic receipt number (RCT-00001); click it to print. |
| **Notes / details** | Anything else worth keeping on that record. |
| **Remove** | Tick and save to delete a row (administrators only). |

**Adding space when the table fills up** — three ways:

- **+ Add row** adds one blank row, **+ Add 5 rows** adds five at once, as often as you like.
- **Rows per page** at the top switches the table between 25, 50, 100, 200 and 500 rows, so a full page holds far more.
- **Show more space** in the header jumps straight to 500 rows per page. Use **Next** at the bottom to page through older records.

**Filling it in**

1. Type into any row — the top row of blank rows is ready, or press **+ Add row** (above the table, next to the column headings) for more.
2. Click **Save** — the blue button in the bar at the bottom of the screen, always in view however long the table gets. One click saves every row on the page, and new rows are given a record and receipt number automatically.
3. Keep working: after saving, type into any row again to correct it and click **Save** once more. You can edit and save as many times as you like — nothing is locked after saving. The live totals at the bottom and the balance in each row update as you type.
4. To find a person, type part of their name, phone, ID, plot, receipt number or notes and press **Search**. The summary shows how many records matched, plus the total price, amount received and balance for them.

Every add, edit and delete is written to the Activity Log. Amounts must be zero or more, and money received can never be more than the total price — the row is highlighted with the reason if it is. The **Receipts** column prints a single record as a receipt for the buyer.

**Retired pages.** Dashboard, Customers, Land Records, Sales, Payments, Receipts, Documents and Reports are no longer shown anywhere in the interface — Records replaces them. Their code and data are still in the project (nothing was deleted and no records were lost), and they remain reachable by typing their address, which keeps the exports and the Settings → Backup page working as your safety net.



## 6. Register customers

Customers → Register customer. Supply full name, phone and registration date; add optional ID, contact and next-of-kin details. Detail pages show linked sales, payments and documents. Customers with sales cannot be deleted.

## 7. Add land

Land Records → Add land. Supply plot, location, size, price, type and date. Use Available or Reserved for unsold plots. Record a sale to mark a plot Sold. Detail pages provide reservation controls and linked transactions.

## 8. Record sales

Sales → Record sale. Choose one customer and one unsold plot, enter the agreed price and date, and optionally enter an initial payment. Saving marks the plot Sold. Each plot can have only one sale. Deleting a paid sale requires explicit confirmation and removes its payment records; avoid deletion for accounting corrections without an approved business policy.

## 9. Record payments and documents

Open a sale → Record payment. Enter a positive amount, date and method. Outstanding is computed from sale price and recorded payments; fully paid sales show zero outstanding. Overpayments are blocked by default; administrators can explicitly override, or enable the global setting. Receipts show the payment and **current** totals, not an immutable historical snapshot. Receipt pages support browser print and PDF.

Documents → Upload document. Link at least one customer, land or sale. Allowed extensions and a 10 MB size limit are enforced, but files are not malware-scanned. Download using the authenticated document route. Delete permissions are role-gated.

## 10. Reports and search

Reports provides sales, payments, outstanding balances, available/sold land, customers and monthly summaries. Choose a preset period, or choose Custom dates and enter both dates. Export CSV, Excel or PDF; print uses browser print styles. Global search returns up to 25 matches per category. Administrator/manager Activity Log shows actions recorded through application views; it is not a tamper-proof ledger.

## 11. Backup and restore

See `C:\Users\MacBook Pro\Desktop\land\README_DEPLOYMENT.md`, section 11, for full backup and restoration instructions. JSON/CSV exports are not full backups: preserve the database, private media and configuration together, and test restoration.

## 12. Deploy and verify

**First deployment, or seeing `404 NOT_FOUND` after a deploy? Read `DEPLOY.md`** — it explains why a static host (Vercel/Netlify) cannot run Django, gives the step-by-step Render setup with the exact build and start commands, the environment variables and the database, and how to create your first administrator in the cloud.

See `C:\Users\MacBook Pro\Desktop\land\README_DEPLOYMENT.md`, section 12, for production configuration, verification commands and release limitations. Do not publish the development server or assume passing local tests establishes production readiness.
