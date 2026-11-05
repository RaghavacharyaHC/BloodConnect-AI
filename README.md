# BloodConnect — Blood Donor and Emergency Blood Availability Portal

A community-driven portal designed for college campuses and local neighborhoods to connect volunteer blood donors, emergency patients/attendants, and hospital blood banks rapidly, safely, and transparently.

---

## 🎯 Technology Stack
- **Frontend**: HTML5, Vanilla CSS3 (Custom responsive red/white design system), Vanilla JavaScript (ES6)
- **Backend**: Python 3 (Flask) with `ProxyFix` reverse-proxy header support
- **Serverless Runtime**: Vercel Serverless Functions (`api/index.py` WSGI handler with `vercel.json`)
- **Database (Dual Engine)**:
  - **Hosted Production**: PostgreSQL (Neon, Supabase, Vercel Postgres, AWS RDS) via `psycopg2-binary`
  - **Local Development**: SQLite with foreign key enforcement and automatic fallback
  - **Schema Safety**: Fully idempotent `CREATE TABLE IF NOT EXISTS` initialization (never drops or deletes data)
- **QR Generation**: Python `qrcode` + `Pillow` (Encodes secure token URL with public HTTPS origin; zero PII stored in QR matrix)
- **Security**: `werkzeug.security` salted password hashing (PBKDF2/SHA256) & session-based role authorization

---

## 👥 Main User Roles
1. **Donor**: Volunteer students and community members with a digital donor ID, masked contact details, and QR verification pass.
2. **Patient / Attendant**: Search available units across community volunteers and regional blood banks.
3. **Hospital / Blood Bank Staff**: Authorized clinicians who authenticate to verify donor eligibility and record genuine donations.
4. **Administrator**: System administration, statistics, and audit logging.

---

## 📁 Project Structure

```text
BloodConnect/
│
├── api/
│   └── index.py            # Vercel Serverless Function WSGI entry point
├── app.py                  # Main Flask application with routing, ProxyFix & auth logic
├── database.py             # Dual PostgreSQL & SQLite database engine with parameterized queries
├── qr_service.py           # QR code generation service (URL-only encoding)
├── requirements.txt        # Python dependency manifest (Flask, qrcode, pillow, psycopg2-binary)
├── vercel.json             # Vercel routing configuration routing requests to api/index.py
├── .env.example            # Environment variable template with placeholder values
├── .gitignore              # Git ignore rules for secrets, DBs, venvs, and build artifacts
├── README.md               # Complete setup, PostgreSQL, GitHub & Vercel deployment guide
├── test_app.py             # Automated unit test suite (22 comprehensive test cases)
├── verify_startup.py       # Live HTTP socket verification script
│
├── static/
│   ├── css/
│   │   └── style.css       # Clean Red, White & Light-Neutral design system + print styles
│   └── js/
│       └── main.js         # Navigation toggle, city chips & form handling
│
└── templates/
    ├── base.html           # Base layout with header, navigation, flash alerts & footer
    ├── index.html          # Homepage with Hero, Blood Search form, and Stats
    ├── search.html         # Availability search (community donors + sample hospital reserves)
    ├── become_donor.html   # Functional donor registration form with validation
    ├── donor_card.html     # Digital Donor ID pass with embedded QR code & print view
    ├── donor_profile.html  # Secure QR-scanned public profile (strictly approved fields)
    └── login.html          # Multi-role authentication (Donor & Hospital Staff)
```

---

## 🔒 Security & Privacy Architecture

1. **Unpredictable Token QR Codes & Public HTTPS Origins**:
   - The generated QR code strictly encodes an unpredictable URL (e.g. `https://your-domain.vercel.app/donor/profile/<token>`).
   - *Zero Personally Identifiable Information (no name, phone, or email)* is encoded inside the QR image matrix.
   - Automatically resolves public HTTPS domain using `PUBLIC_BASE_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, `VERCEL_URL`, or `ProxyFix` headers.
2. **Contact Shielding & Masking**:
   - Public pages mask phone numbers (e.g. `+91 98*****210`) to prevent spam and unsolicited contact.
   - Email addresses and clinical donation histories are never exposed on public profile views.
3. **Salted Password Hashing**:
   - All passwords are encrypted with salted hashes using `werkzeug.security.generate_password_hash`.
   - Plaintext passwords are never stored.
4. **Authorized Donation Logging**:
   - Unauthenticated or non-staff users cannot create or verify donations (`HTTP 403 Forbidden`).
   - Donations can only be marked `is_verified = 1` through authorized staff actions.

---

## ⚙️ Environment Variables Reference

Copy `.env.example` to `.env` for local testing:

```powershell
cp .env.example .env
```

| Variable | Required in Prod | Description | Example Value |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | Flask session cookie encryption key (min 32 chars) | `secrets.token_hex(32)` |
| `DATABASE_URL` | **Yes** (Prod) | Hosted PostgreSQL connection string | `postgresql://user:pass@ep-host.neon.tech/db?sslmode=require` |
| `PUBLIC_BASE_URL` | Recommended | Canonical HTTPS public origin for QR codes & profile links | `https://bloodconnect.vercel.app` |
| `BLOODCONNECT_DB` | No | Custom local SQLite file path (defaults to `bloodconnect.db`) | `bloodconnect.db` |
| `FLASK_ENV` | Optional | Application runtime environment (`production` / `development`) | `production` |
| `FLASK_DEBUG` | Optional | Flask debug mode flag (`0` for production) | `0` |

---

## 💻 Windows Local Setup & Run Instructions

Follow these step-by-step instructions in Windows PowerShell:

### 1. Open Terminal in the Project Directory
```powershell
cd C:\Users\WIN10\Desktop\BloodConnect
```

### 2. Create & Activate a Python Virtual Environment
```powershell
# Create the virtual environment named 'venv'
python -m venv venv

# Activate on Windows PowerShell:
.\venv\Scripts\Activate.ps1
```

> **Note for PowerShell execution policy:** If you encounter a script execution error, run:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and then re-run the activation command.

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Run the Application Locally (Uses SQLite by default)
```powershell
python app.py
```

### 5. Access BloodConnect in Your Browser
- **Homepage & Search**: [http://127.0.0.1:5000](http://127.0.0.1:5000)
- **Become a Donor (Registration)**: [http://127.0.0.1:5000/become-donor](http://127.0.0.1:5000/become-donor)
- **Find Blood Availability**: [http://127.0.0.1:5000/find-blood](http://127.0.0.1:5000/find-blood)
- **Portal Sign In**: [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login)
- **System Health Check API**: [http://127.0.0.1:5000/health](http://127.0.0.1:5000/health)

---

## 🗄️ Hosted PostgreSQL Setup Guide

Because Vercel serverless functions have a read-only, ephemeral filesystem, **a hosted PostgreSQL database is required for production persistence**.

### Recommended Free Hosted PostgreSQL Providers:
1. **Neon** ([neon.tech](https://neon.tech)) — Generous free tier, instant serverless PostgreSQL, zero configuration.
2. **Supabase** ([supabase.com](https://supabase.com)) — Free tier PostgreSQL database with connection pooling.
3. **Vercel Postgres** ([vercel.com/storage/postgres](https://vercel.com/storage/postgres)) — Native Vercel integration powered by Neon.

### Setup Steps:
1. Create a database instance on your chosen provider.
2. Copy the connection string (URI). It will look like:
   ```text
   postgresql://username:password@ep-your-database-id.region.neon.tech/neondb?sslmode=require
   ```
3. Add this connection URI as the `DATABASE_URL` environment variable:
   - Locally: in your `.env` file
   - In Vercel: in **Project Settings > Environment Variables**
4. **Schema Initialization is Automatic**: The app runs `init_db()` upon startup, creating the `donors`, `donation_history`, and `staff_users` tables automatically without dropping or wiping any existing data.

---

## 🐙 GitHub Preparation

Before deploying to Vercel, prepare and push your code to a private or public GitHub repository:

### 1. Initialize Git Repository (if not already initialized)
```powershell
git init
```

### 2. Verify `.gitignore`
Make sure sensitive files are ignored before staging:
```powershell
git status
```
Confirm that `bloodconnect.db`, `.env`, and `venv/` are **NOT** tracked by git.

### 3. Commit Code
```powershell
git add .
git commit -m "feat: prepare BloodConnect for Vercel deployment with dual-engine DB and public HTTPS origin"
```

### 4. Push to GitHub
```powershell
git remote add origin https://github.com/<your-username>/BloodConnect.git
git branch -M main
git push -u origin main
```

---

## 🚀 Vercel Deployment Instructions

### Method A: Deploy via Vercel Web Dashboard (Recommended)

1. Log in to your [Vercel Dashboard](https://vercel.com).
2. Click **Add New...** > **Project**.
3. Import your **BloodConnect** GitHub repository.
4. In the Project Configuration screen:
   - **Framework Preset**: Select **Other** (Vercel automatically detects the Python runtime from `vercel.json` and `api/index.py`).
   - **Root Directory**: Leave as `./`.
5. Under **Environment Variables**, add the following:
   - `SECRET_KEY`: A strong 64-character hex string (e.g., generated with `python -c "import secrets; print(secrets.token_hex(32))"`).
   - `DATABASE_URL`: Your hosted PostgreSQL connection URI (e.g. from Neon or Supabase).
   - `PUBLIC_BASE_URL`: (Optional) Your custom domain or Vercel URL (e.g. `https://bloodconnect.vercel.app`). If omitted, Vercel's production URL is detected automatically.
6. Click **Deploy**.
7. Once deployed, test the live deployment:
   - Visit `https://<your-project>.vercel.app/health` to confirm `{"status": "healthy", "database": "connected"}`.
   - Register a volunteer donor at `/become-donor` and verify that the Digital ID card and QR code render properly.
   - Scan the QR code to ensure it opens the public profile on your production HTTPS domain.

---

### Method B: Deploy via Vercel CLI

1. Install Vercel CLI globally:
   ```powershell
   npm install -g vercel
   ```
2. Log in to Vercel:
   ```powershell
   vercel login
   ```
3. Link your project:
   ```powershell
   vercel link
   ```
4. Add environment variables:
   ```powershell
   vercel env add SECRET_KEY production
   vercel env add DATABASE_URL production
   vercel env add PUBLIC_BASE_URL production
   ```
5. Deploy to production:
   ```powershell
   vercel --prod
   ```

---

## 🧪 Automated Test Suite

Run the full automated test suite anytime using Python's built-in `unittest`:

```powershell
python -m unittest -v test_app.py
```

### What is tested (22 Test Cases):
1. **Health Check & DB Status**: Verifies `/health` returns HTTP 200 and `"database": "connected"`.
2. **Homepage & Brand Elements**: Verifies navigation, hero section, and branding.
3. **Donor Search**: Tests search filtering across community donors and demo blood banks.
4. **Valid Donor Registration**: Tests full registration workflow and digital ID pass issuance.
5. **Input Validation**: Tests rejection of invalid blood groups, underage (<18) or overage (>65) donors.
6. **Field Length Validations**: Enforces minimum name, city, phone length constraints.
7. **Duplicate Prevention**: Rejects duplicate emails and phone numbers with descriptive errors.
8. **Digital Donor ID Card**: Verifies card view with masked phone number and issue date.
9. **QR Image Streaming**: Validates that `/donor/qr/<token>.png` returns valid PNG bytes (`b'\x89PNG'`).
10. **Public Profile Privacy**: Ensures email, unmasked phone, and clinical history are shielded.
11. **Phone Number Masking**: Tests formatting rules (e.g. `9876543210` -> `98*****210`).
12. **Unauthorized Donation Prevention**: Unauthenticated requests receive HTTP 403 Forbidden.
13. **Authorized Staff Verification**: Verifies staff login and donation logging with `is_verified = 1`.
14. **Custom Public URL Resolution**: Tests `PUBLIC_BASE_URL` override for production QR generation.
15. **Vercel Production URL Resolution**: Tests `VERCEL_PROJECT_PRODUCTION_URL` HTTPS origin resolution.
16. **Vercel Preview URL Resolution**: Tests `VERCEL_URL` branch/preview URL resolution.
17. **Local URL Fallback**: Tests fallback to standard request host in local offline development.
18. **QR PNG with Production URL**: Validates QR PNG generation targeting external production URL.
19. **Database Engine Detection**: Verifies auto-switching between SQLite and PostgreSQL.
20. **PostgreSQL URL Normalization**: Tests normalization of `postgres://` to `postgresql://`.
21. **Idempotent Schema Initialization**: Verifies `init_db()` never drops or wipes existing data.
22. **Static Asset Serving & MIME Types**: Verifies `/static/css/style.css` (`text/css`) and `/static/js/main.js` (`text/javascript`).
23. **Vercel Entry Point Export**: Verifies `api/index.py` cleanly exports the application WSGI instance.

To run the live HTTP socket startup verification script:
```powershell
python verify_startup.py
```
