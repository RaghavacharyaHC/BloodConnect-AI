"""
BloodConnect Milestone 2 Automated Test Suite
Tests:
- Route availability & health check
- Successful donor registration with SQLite persistence
- Invalid input validation (blood group, age, email, phone)
- Duplicate registration handling (email and phone uniqueness)
- QR code generation and profile URL target
- Public QR profile privacy: approved public fields only, sensitive PII shielded
- Phone number masking on donor ID card
- Prevention of unauthorized donation verification (HTTP 403 Forbidden)
- Authorized staff donation verification with password hashing
"""

import os
import tempfile
import unittest
import json
from werkzeug.security import check_password_hash

# Set test database path before importing app/database modules
TEMP_DIR = tempfile.mkdtemp()
TEST_DB_PATH = os.path.join(TEMP_DIR, "test_bloodconnect.db")
os.environ["BLOODCONNECT_DB"] = TEST_DB_PATH

from app import app, get_public_url, get_secret_key, INSECURE_DEV_SECRET_KEY
from database import (
    init_db,
    get_db,
    create_donor,
    get_donor_by_id,
    get_donor_by_token,
    create_staff_user,
    get_donor_donations,
    get_database_engine,
    normalize_postgres_url,
)


class BloodConnectMilestone2TestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key-12345"

    def setUp(self):
        # Fresh database for each test
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        init_db(TEST_DB_PATH)
        self.client = app.test_client()

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    # ---------------------------------------------------------
    # Baseline Existing Route Tests
    # ---------------------------------------------------------

    def test_health_check(self):
        """Verify that /health returns HTTP 200 and healthy DB status."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("database"), "connected")
        self.assertEqual(data.get("app"), "BloodConnect")

    def test_home_page(self):
        """Verify that homepage loads with HTTP 200 and key branding elements."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("BloodConnect", html)
        self.assertIn("Find Blood", html)
        self.assertIn("Become a Donor", html)
        self.assertIn("Login", html)

    def test_search_page_with_sample_and_registered_donors(self):
        """Verify that searching for blood shows results and community donors."""
        # First register a demo donor
        create_donor(
            name="Sample Campus Volunteer",
            blood_group="O+",
            age=21,
            phone="9876500001",
            email="sample.volunteer@college.edu",
            city="Mumbai",
            db_path=TEST_DB_PATH,
        )

        response = self.client.get("/find-blood?blood_group=O%2B&city=Mumbai&units=1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # Check that registered community donor is listed with masked phone
        self.assertIn("Sample Campus Volunteer", html)
        self.assertIn("9876*****001", html)
        # Check that demo blood bank is listed with sample note
        self.assertIn("City Life Blood Bank", html)
        self.assertIn("Sample / Demo Stock", html)

    # ---------------------------------------------------------
    # Donor Registration & Database Persistence Tests
    # ---------------------------------------------------------

    def test_donor_registration_success(self):
        """Verify successful donor registration and SQLite persistence."""
        payload = {
            "name": "Alex Morgan",
            "blood_group": "A+",
            "age": "23",
            "city": "Bengaluru",
            "phone": "9812345678",
            "email": "alex.morgan@college.edu",
            "password": "SecurePassword123!",
        }
        response = self.client.post("/become-donor", data=payload, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # Should redirect to Digital ID card page
        self.assertIn("Digital Donor Identity Card", html)
        self.assertIn("Alex Morgan", html)
        self.assertIn("A+", html)
        self.assertIn("Bengaluru", html)

        # Verify record exists in SQLite
        conn = get_db(TEST_DB_PATH)
        row = conn.execute("SELECT * FROM donors WHERE email = ?", ("alex.morgan@college.edu",)).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "Alex Morgan")
        self.assertEqual(row["blood_group"], "A+")
        self.assertEqual(row["age"], 23)
        self.assertTrue(row["donor_id"].startswith("BC-2026-"))
        self.assertIsNotNone(row["qr_token"])
        self.assertGreater(len(row["qr_token"]), 20)

        # Verify password is hashed, NOT plaintext
        self.assertNotEqual(row["password_hash"], "SecurePassword123!")
        self.assertTrue(check_password_hash(row["password_hash"], "SecurePassword123!"))

    def test_donor_registration_invalid_blood_group(self):
        """Verify rejection of invalid blood group."""
        payload = {
            "name": "Invalid Blood Donor",
            "blood_group": "Z_POSITIVE",
            "age": "25",
            "city": "Pune",
            "phone": "9800000001",
            "email": "invalid.bg@college.edu",
        }
        response = self.client.post("/become-donor", data=payload)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Invalid blood group", html)

        # Verify database is empty
        conn = get_db(TEST_DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_donor_registration_invalid_age(self):
        """Verify rejection of donor age outside medical window (18-65)."""
        # Test under-age
        response = self.client.post("/become-donor", data={
            "name": "Young Donor",
            "blood_group": "B+",
            "age": "16",
            "city": "Delhi",
            "phone": "9800000002",
            "email": "young@college.edu",
        })
        self.assertIn("between 18 and 65", response.get_data(as_text=True))

        # Test over-age
        response = self.client.post("/become-donor", data={
            "name": "Senior Donor",
            "blood_group": "B+",
            "age": "72",
            "city": "Delhi",
            "phone": "9800000003",
            "email": "senior@college.edu",
        })
        self.assertIn("between 18 and 65", response.get_data(as_text=True))

    def test_duplicate_registration_prevention(self):
        """Verify duplicate email or phone number is rejected."""
        create_donor(
            name="First Donor",
            blood_group="O+",
            age=22,
            phone="9876543210",
            email="existing@college.edu",
            city="Mumbai",
            db_path=TEST_DB_PATH,
        )

        # Attempt same email
        resp_email = self.client.post("/become-donor", data={
            "name": "Duplicate Email Donor",
            "blood_group": "A+",
            "age": "24",
            "city": "Pune",
            "phone": "9876543299",
            "email": "existing@college.edu",
        })
        self.assertIn("email address is already registered", resp_email.get_data(as_text=True))

        # Attempt same phone
        resp_phone = self.client.post("/become-donor", data={
            "name": "Duplicate Phone Donor",
            "blood_group": "A+",
            "age": "24",
            "city": "Pune",
            "phone": "9876543210",
            "email": "new.different@college.edu",
        })
        self.assertIn("phone number is already registered", resp_phone.get_data(as_text=True))

    # ---------------------------------------------------------
    # QR Code & Profile Privacy Tests
    # ---------------------------------------------------------

    def test_qr_code_image_endpoint(self):
        """Verify that QR endpoint produces a valid PNG image byte stream."""
        donor = create_donor(
            name="QR Test Donor",
            blood_group="AB+",
            age=25,
            phone="9811122233",
            email="qr.test@college.edu",
            city="Chennai",
            db_path=TEST_DB_PATH,
        )

        response = self.client.get(f"/donor/qr/{donor['qr_token']}.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/png")
        # Check standard PNG header signature: \x89PNG\r\n\x1a\n
        self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_public_qr_profile_privacy_shield(self):
        """
        Verify QR-linked profile page:
        - Displays explicitly approved public fields (Name, Blood Group, City, ID, Status)
        - DOES NOT expose email, full phone number, or donation history
        """
        donor = create_donor(
            name="Private Donor Profile",
            blood_group="O-",
            age=28,
            phone="9822233344",
            email="strictly.secret@college.edu",
            city="Hyderabad",
            db_path=TEST_DB_PATH,
        )

        response = self.client.get(f"/donor/profile/{donor['qr_token']}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # 1. Approved public fields MUST be present
        self.assertIn("Private Donor Profile", html)
        self.assertIn("O-", html)
        self.assertIn("Hyderabad", html)
        self.assertIn(donor["donor_id"], html)
        self.assertIn("Active Registered Donor", html)

        # 2. Sensitive fields MUST NOT be present
        self.assertNotIn("strictly.secret@college.edu", html)
        self.assertNotIn("9822233344", html)  # Raw unmasked phone must never appear
        self.assertNotIn("donation_history", html)

    def test_donor_id_card_phone_masking(self):
        """Verify that the Donor ID card masks the personal contact number."""
        donor = create_donor(
            name="Card Display Donor",
            blood_group="B-",
            age=22,
            phone="9876543210",
            email="card.donor@college.edu",
            city="Delhi",
            db_path=TEST_DB_PATH,
        )

        response = self.client.get(f"/donor/card/{donor['donor_id']}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("Card Display Donor", html)
        self.assertIn("B-", html)
        # Should display masked phone, NOT full phone
        self.assertIn("9876*****210", html)
        self.assertNotIn(">9876543210<", html)

    # ---------------------------------------------------------
    # Donation Verification & Authorization Security Tests
    # ---------------------------------------------------------

    def test_prevention_of_unauthorized_donation_verification(self):
        """
        Verify that unauthorized users CANNOT record or mark donations verified.
        Expects HTTP 403 Forbidden.
        """
        donor = create_donor(
            name="Recipient Donor",
            blood_group="A+",
            age=20,
            phone="9833344455",
            email="recipient.donor@college.edu",
            city="Mumbai",
            db_path=TEST_DB_PATH,
        )

        # Attempt to verify without staff session
        unauthorized_payload = {
            "donor_id": donor["donor_id"],
            "hospital_name": "Unauthorized Clinic",
            "donation_date": "2026-10-20",
            "units": 1,
        }
        response = self.client.post(
            "/api/verify-donation",
            data=json.dumps(unauthorized_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertIn("Hospital staff authentication required", data.get("error", ""))

        # Verify NO donation records exist in SQLite
        donations = get_donor_donations(donor["donor_id"], db_path=TEST_DB_PATH)
        self.assertEqual(len(donations), 0)

    def test_authorized_staff_donation_verification(self):
        """
        Verify that authorized hospital staff with hashed credentials
        can legitimately record a verified donation.
        """
        donor = create_donor(
            name="Verified Test Volunteer",
            blood_group="O+",
            age=22,
            phone="9844455566",
            email="verified.donor@college.edu",
            city="Pune",
            db_path=TEST_DB_PATH,
        )

        # Create authorized staff user with hashed password
        create_staff_user(
            staff_id="STF-PUNE-01",
            name="Dr. Anita Desai",
            email="dr.anita@cityhospital.org",
            hospital_name="Pune General Hospital",
            password="HospitalStaffPass999!",
            db_path=TEST_DB_PATH,
        )

        # Simulate staff login session
        with self.client.session_transaction() as sess:
            sess["is_staff"] = True
            sess["staff_id"] = "STF-PUNE-01"
            sess["staff_name"] = "Dr. Anita Desai"
            sess["hospital_name"] = "Pune General Hospital"

        verify_payload = {
            "donor_id": donor["donor_id"],
            "hospital_name": "Pune General Hospital",
            "donation_date": "2026-10-20",
            "units": 1,
        }
        response = self.client.post(
            "/api/verify-donation",
            data=json.dumps(verify_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        res_data = response.get_json()
        self.assertEqual(res_data["status"], "success")

        # Verify donation record in SQLite has is_verified = 1 and verified_by_staff_id set
        donations = get_donor_donations(donor["donor_id"], db_path=TEST_DB_PATH)
        self.assertEqual(len(donations), 1)
        self.assertEqual(donations[0]["is_verified"], 1)
        self.assertEqual(donations[0]["verified_by_staff_id"], "STF-PUNE-01")
        self.assertEqual(donations[0]["hospital_name"], "Pune General Hospital")

    # ---------------------------------------------------------
    # Milestone 3 / Vercel & Production Readiness Test Cases
    # ---------------------------------------------------------

    def test_public_url_resolution_with_custom_base(self):
        """Verify that PUBLIC_BASE_URL overrides origin for production QR & profile URLs."""
        old_val = os.environ.get("PUBLIC_BASE_URL")
        try:
            os.environ["PUBLIC_BASE_URL"] = "https://bloodconnect-college.vercel.app"
            with app.test_request_context():
                resolved_url = get_public_url("donor_profile", token="test-safe-token-123")
                self.assertEqual(resolved_url, "https://bloodconnect-college.vercel.app/donor/profile/test-safe-token-123")
        finally:
            if old_val is not None:
                os.environ["PUBLIC_BASE_URL"] = old_val
            else:
                os.environ.pop("PUBLIC_BASE_URL", None)

    def test_public_url_resolution_with_vercel_prod_url(self):
        """Verify that VERCEL_PROJECT_PRODUCTION_URL automatically supplies public HTTPS origin."""
        old_base = os.environ.pop("PUBLIC_BASE_URL", None)
        old_prod = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
        try:
            os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = "bloodconnect.vercel.app"
            with app.test_request_context():
                resolved_url = get_public_url("donor_profile", token="test-token-456")
                self.assertEqual(resolved_url, "https://bloodconnect.vercel.app/donor/profile/test-token-456")
        finally:
            if old_base is not None:
                os.environ["PUBLIC_BASE_URL"] = old_base
            if old_prod is not None:
                os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = old_prod
            else:
                os.environ.pop("VERCEL_PROJECT_PRODUCTION_URL", None)

    def test_public_url_resolution_with_vercel_preview_url(self):
        """Verify that VERCEL_URL is used as fallback for preview/branch deployments."""
        old_base = os.environ.pop("PUBLIC_BASE_URL", None)
        old_prod = os.environ.pop("VERCEL_PROJECT_PRODUCTION_URL", None)
        old_preview = os.environ.get("VERCEL_URL")
        try:
            os.environ["VERCEL_URL"] = "bloodconnect-git-preview.vercel.app"
            with app.test_request_context():
                resolved_url = get_public_url("donor_profile", token="test-token-789")
                self.assertEqual(resolved_url, "https://bloodconnect-git-preview.vercel.app/donor/profile/test-token-789")
        finally:
            if old_base is not None:
                os.environ["PUBLIC_BASE_URL"] = old_base
            if old_prod is not None:
                os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = old_prod
            if old_preview is not None:
                os.environ["VERCEL_URL"] = old_preview
            else:
                os.environ.pop("VERCEL_URL", None)

    def test_public_url_resolution_local_fallback(self):
        """Verify that in local dev with no Vercel env vars, standard request URL is used."""
        old_base = os.environ.pop("PUBLIC_BASE_URL", None)
        old_prod = os.environ.pop("VERCEL_PROJECT_PRODUCTION_URL", None)
        old_preview = os.environ.pop("VERCEL_URL", None)
        try:
            with app.test_request_context(base_url="http://127.0.0.1:5000"):
                resolved_url = get_public_url("donor_profile", token="test-local-token")
                self.assertEqual(resolved_url, "http://127.0.0.1:5000/donor/profile/test-local-token")
        finally:
            if old_base is not None:
                os.environ["PUBLIC_BASE_URL"] = old_base
            if old_prod is not None:
                os.environ["VERCEL_PROJECT_PRODUCTION_URL"] = old_prod
            if old_preview is not None:
                os.environ["VERCEL_URL"] = old_preview

    def test_qr_png_generation_with_production_url(self):
        """Verify QR PNG generation works with custom public HTTPS URL set."""
        donor = create_donor(
            name="QR Prod Test Donor",
            blood_group="AB+",
            age=25,
            phone="9877788899",
            email="qr.prod@college.edu",
            city="Mumbai",
            db_path=TEST_DB_PATH,
        )

        old_base = os.environ.get("PUBLIC_BASE_URL")
        try:
            os.environ["PUBLIC_BASE_URL"] = "https://bloodconnect.vercel.app"
            response = self.client.get(f"/donor/qr/{donor['qr_token']}.png")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            # Verify PNG binary magic bytes header: \x89PNG\r\n\x1a\n
            self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))
        finally:
            if old_base is not None:
                os.environ["PUBLIC_BASE_URL"] = old_base
            else:
                os.environ.pop("PUBLIC_BASE_URL", None)

    def test_database_engine_detection(self):
        """Verify get_database_engine correctly identifies sqlite and postgres modes."""
        # 1. Explicit db_path always forces sqlite
        self.assertEqual(get_database_engine(TEST_DB_PATH), "sqlite")

        # 2. No DATABASE_URL or POSTGRES_URL defaults to sqlite
        old_db_url = os.environ.pop("DATABASE_URL", None)
        old_pg_url = os.environ.pop("POSTGRES_URL", None)
        try:
            self.assertEqual(get_database_engine(None), "sqlite")

            # 3. Setting DATABASE_URL to postgresql:// detects postgres
            os.environ["DATABASE_URL"] = "postgresql://user:pass@host:5432/db"
            self.assertEqual(get_database_engine(None), "postgres")

            # 4. Setting DATABASE_URL to postgres:// detects postgres
            os.environ["DATABASE_URL"] = "postgres://user:pass@host:5432/db"
            self.assertEqual(get_database_engine(None), "postgres")
        finally:
            if old_db_url is not None:
                os.environ["DATABASE_URL"] = old_db_url
            else:
                os.environ.pop("DATABASE_URL", None)
            if old_pg_url is not None:
                os.environ["POSTGRES_URL"] = old_pg_url

    def test_postgres_url_normalization(self):
        """Verify normalize_postgres_url converts postgres:// to postgresql:// and ensures sslmode=require."""
        legacy_url = "postgres://usr:pwd@ep-test.neon.tech/neondb?sslmode=require"
        normalized = normalize_postgres_url(legacy_url)
        self.assertTrue(normalized.startswith("postgresql://"))

        standard_url = "postgresql://usr:pwd@ep-test.neon.tech/neondb?sslmode=require"
        self.assertEqual(normalize_postgres_url(standard_url), standard_url)

        # Ensure sslmode=require is automatically appended for cloud databases like Neon
        url_without_ssl = "postgres://usr:pwd@ep-test.neon.tech/neondb"
        self.assertEqual(
            normalize_postgres_url(url_without_ssl),
            "postgresql://usr:pwd@ep-test.neon.tech/neondb?sslmode=require"
        )

    def test_schema_initialization_idempotent_and_non_destructive(self):
        """Verify that init_db can be called repeatedly without dropping existing data."""
        # Create a donor
        donor = create_donor(
            name="Persistent Volunteer",
            blood_group="B+",
            age=28,
            phone="9811122233",
            email="persistent@college.edu",
            city="Delhi",
            db_path=TEST_DB_PATH,
        )

        # Call init_db again (simulating app restart or serverless cold start)
        init_db(TEST_DB_PATH)

        # Confirm donor is still intact in the database
        retrieved = get_donor_by_id(donor["donor_id"], db_path=TEST_DB_PATH)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], "Persistent Volunteer")
        self.assertEqual(retrieved["email"], "persistent@college.edu")

    def test_static_css_and_js_serving(self):
        """Verify that static CSS and JavaScript files are served with HTTP 200 and proper MIME types."""
        # Test CSS
        css_res = self.client.get("/static/css/style.css")
        self.assertEqual(css_res.status_code, 200)
        self.assertIn("text/css", css_res.content_type)
        self.assertIn("--primary: #DC2626", css_res.get_data(as_text=True))
        css_res.close()

        # Test JS
        js_res = self.client.get("/static/js/main.js")
        self.assertEqual(js_res.status_code, 200)
        self.assertIn("javascript", js_res.content_type)
        js_res.close()

    def test_vercel_api_entrypoint_import(self):
        """Verify that api/index.py imports cleanly and exports the identical Flask app instance."""
        from api.index import app as vercel_app
        self.assertIs(vercel_app, app)

    # ---------------------------------------------------------
    # Production SECRET_KEY Security & Vercel Config Tests
    # ---------------------------------------------------------

    def test_production_missing_secret_key_raises_runtime_error(self):
        """Verify that running in production without SECRET_KEY strictly raises a RuntimeError."""
        old_env = os.environ.get("FLASK_ENV")
        old_key = os.environ.get("SECRET_KEY")
        try:
            os.environ["FLASK_ENV"] = "production"
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaises(RuntimeError) as ctx:
                get_secret_key()
            self.assertIn("mandatory in production", str(ctx.exception))
        finally:
            if old_env is not None:
                os.environ["FLASK_ENV"] = old_env
            else:
                os.environ.pop("FLASK_ENV", None)
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_vercel_missing_secret_key_raises_runtime_error(self):
        """Verify that running on Vercel (VERCEL=1) without SECRET_KEY strictly raises a RuntimeError."""
        old_vercel = os.environ.get("VERCEL")
        old_key = os.environ.get("SECRET_KEY")
        try:
            os.environ["VERCEL"] = "1"
            os.environ.pop("SECRET_KEY", None)
            with self.assertRaises(RuntimeError) as ctx:
                get_secret_key()
            self.assertIn("mandatory in production", str(ctx.exception))
        finally:
            if old_vercel is not None:
                os.environ["VERCEL"] = old_vercel
            else:
                os.environ.pop("VERCEL", None)
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_production_insecure_default_secret_key_raises_runtime_error(self):
        """Verify that providing known default or insecure keys in production raises RuntimeError."""
        old_env = os.environ.get("FLASK_ENV")
        old_key = os.environ.get("SECRET_KEY")
        try:
            os.environ["FLASK_ENV"] = "production"
            insecure_keys = [
                INSECURE_DEV_SECRET_KEY,
                "bloodconnect-community-secret-key-2026",
                "secret",
                "changeme",
            ]
            for bad_key in insecure_keys:
                os.environ["SECRET_KEY"] = bad_key
                with self.assertRaises(RuntimeError) as ctx:
                    get_secret_key()
                self.assertIn("insecure, default secret key", str(ctx.exception))
        finally:
            if old_env is not None:
                os.environ["FLASK_ENV"] = old_env
            else:
                os.environ.pop("FLASK_ENV", None)
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_production_short_secret_key_raises_runtime_error(self):
        """Verify that providing an insufficiently strong (<16 chars) key in production raises RuntimeError."""
        old_env = os.environ.get("FLASK_ENV")
        old_key = os.environ.get("SECRET_KEY")
        try:
            os.environ["FLASK_ENV"] = "production"
            os.environ["SECRET_KEY"] = "short-key-123"
            with self.assertRaises(RuntimeError) as ctx:
                get_secret_key()
            self.assertIn("at least 16 characters long", str(ctx.exception))
        finally:
            if old_env is not None:
                os.environ["FLASK_ENV"] = old_env
            else:
                os.environ.pop("FLASK_ENV", None)
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_production_valid_secret_key_accepted(self):
        """Verify that a strong key in production is accepted without errors."""
        old_env = os.environ.get("FLASK_ENV")
        old_key = os.environ.get("SECRET_KEY")
        try:
            strong_key = "a-very-strong-production-key-9999-secure-random-64-bytes-token"
            os.environ["FLASK_ENV"] = "production"
            os.environ["SECRET_KEY"] = strong_key
            self.assertEqual(get_secret_key(), strong_key)
        finally:
            if old_env is not None:
                os.environ["FLASK_ENV"] = old_env
            else:
                os.environ.pop("FLASK_ENV", None)
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_local_dev_secret_key_fallback_allowed(self):
        """Verify that local development mode falls back conveniently without failing."""
        old_env = os.environ.pop("FLASK_ENV", None)
        old_vercel = os.environ.pop("VERCEL", None)
        old_debug = os.environ.pop("FLASK_DEBUG", None)
        old_key = os.environ.pop("SECRET_KEY", None)
        try:
            key = get_secret_key()
            self.assertEqual(key, INSECURE_DEV_SECRET_KEY)
        finally:
            if old_env is not None:
                os.environ["FLASK_ENV"] = old_env
            if old_vercel is not None:
                os.environ["VERCEL"] = old_vercel
            if old_debug is not None:
                os.environ["FLASK_DEBUG"] = old_debug
            if old_key is not None:
                os.environ["SECRET_KEY"] = old_key

    def test_vercel_json_configuration_valid_and_includes_assets(self):
        """Verify vercel.json contains valid configuration and bundles templates and static files."""
        vercel_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vercel.json")
        self.assertTrue(os.path.exists(vercel_json_path), "vercel.json must exist in project root")

        with open(vercel_json_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 1. Verify schema and rewrites
        self.assertIn("rewrites", config)
        self.assertEqual(config["rewrites"][0]["destination"], "/api/index.py")

        # 2. Verify functions configuration for api/index.py
        self.assertIn("functions", config)
        self.assertIn("api/index.py", config["functions"])
        include_files = config["functions"]["api/index.py"].get("includeFiles", [])
        self.assertIn("templates/**", include_files)
        self.assertIn("static/**", include_files)


if __name__ == "__main__":
    unittest.main()
