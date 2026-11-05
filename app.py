"""
BloodConnect — Blood Donor and Emergency Blood Availability Portal
College Community Project
Backend: Python Flask with SQLite Persistence & QR Verification
"""

import os
import re
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    flash,
    session,
    abort,
    Response,
)
from werkzeug.security import check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from database import (
    init_db,
    get_db,
    create_donor,
    get_donor_by_id,
    get_donor_by_token,
    get_donor_by_email,
    get_staff_by_email,
    record_verified_donation,
    mask_phone,
    VALID_BLOOD_GROUPS,
)
from qr_service import generate_qr_png_bytes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
INSECURE_DEV_SECRET_KEY = "bloodconnect-dev-insecure-secret-key-change-in-production"


def get_secret_key() -> str:
    """
    Retrieves and validates the Flask SECRET_KEY.
    - In production (FLASK_ENV == 'production', VERCEL environment variable is set, or FLASK_DEBUG == '0'):
      Requires a non-empty, strong SECRET_KEY environment variable.
      Rejects missing, empty, or known default/insecure keys with a RuntimeError.
    - In local development:
      Allows falling back to a development-only key for convenience, while preventing
      any accidental use of this fallback in production.
    """
    is_production = (
        os.environ.get("FLASK_ENV") == "production"
        or os.environ.get("VERCEL") is not None
        or os.environ.get("FLASK_DEBUG") == "0"
    )
    secret_key = os.environ.get("SECRET_KEY", "").strip()

    if is_production:
        if not secret_key:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: The 'SECRET_KEY' environment variable "
                "is mandatory in production (and on Vercel) but is missing or empty. "
                "Generate a strong 64-character secret key and set it in your environment."
            )
        if secret_key in (INSECURE_DEV_SECRET_KEY, "bloodconnect-community-secret-key-2026", "secret", "changeme"):
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: An insecure, default secret key was provided in production. "
                "You must supply a secure, unique SECRET_KEY environment variable."
            )
        if len(secret_key) < 16:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY in production must be at least 16 characters long."
            )
        return secret_key

    # Local development fallback
    return secret_key or INSECURE_DEV_SECRET_KEY


app.secret_key = get_secret_key()

# Apply ProxyFix middleware so Flask correctly detects HTTPS scheme and public host
# when deployed behind reverse proxies such as Vercel, Nginx, or AWS ALB.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Initialize database tables on startup (idempotent, safe on both SQLite and PostgreSQL)
init_db()


def get_public_url(endpoint: str, **values) -> str:
    """
    Builds the canonical external URL for an endpoint, ensuring public HTTPS
    origin in production while preserving local development capability.

    Resolution order:
    1. PUBLIC_BASE_URL (explicitly configured canonical URL e.g. https://bloodconnect.vercel.app)
    2. VERCEL_PROJECT_PRODUCTION_URL (injected automatically by Vercel for production)
    3. VERCEL_URL (injected automatically by Vercel for preview deployments)
    4. url_for(endpoint, _external=True, **values) (local development or standard host)
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if base_url:
        path = url_for(endpoint, **values)
        return f"{base_url.rstrip('/')}{path}"

    vercel_prod = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
    if vercel_prod:
        path = url_for(endpoint, **values)
        return f"https://{vercel_prod.rstrip('/')}{path}"

    vercel_url = os.environ.get("VERCEL_URL", "").strip()
    if vercel_url:
        path = url_for(endpoint, **values)
        return f"https://{vercel_url.rstrip('/')}{path}"

    return url_for(endpoint, _external=True, **values)


app.jinja_env.globals["get_public_url"] = get_public_url

# Sample mock availability data for the blood-bank search demonstration.
# Note: Real-time hospital stock management is planned for future milestones.
SAMPLE_BLOOD_BANKS = [
    {
        "name": "City Life Blood Bank & Hospital",
        "city": "Mumbai",
        "blood_group": "O+",
        "units_available": 12,
        "contact": "+91 98765 43210",
        "status": "Available",
        "is_sample": True,
    },
    {
        "name": "Red Cross District Center",
        "city": "Delhi",
        "blood_group": "A+",
        "units_available": 8,
        "contact": "+91 98765 11223",
        "status": "Available",
        "is_sample": True,
    },
    {
        "name": "Apollo Care Blood Center",
        "city": "Bengaluru",
        "blood_group": "B+",
        "units_available": 15,
        "contact": "+91 98765 99887",
        "status": "Available",
        "is_sample": True,
    },
    {
        "name": "Campus Health Center Blood Reserve",
        "city": "Pune",
        "blood_group": "AB+",
        "units_available": 5,
        "contact": "+91 98765 55443",
        "status": "Available",
        "is_sample": True,
    },
    {
        "name": "Grace Memorial Hospital",
        "city": "Hyderabad",
        "blood_group": "O-",
        "units_available": 3,
        "contact": "+91 98765 33221",
        "status": "Critical Low",
        "is_sample": True,
    },
    {
        "name": "Metropolitan Blood Trust",
        "city": "Chennai",
        "blood_group": "A-",
        "units_available": 4,
        "contact": "+91 98765 77665",
        "status": "Available",
        "is_sample": True,
    },
]


def is_valid_email(email: str) -> bool:
    """Validates email format using regex."""
    if not email:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def is_valid_phone(phone: str) -> bool:
    """Validates phone number has between 10 and 15 digits."""
    if not phone:
        return False
    digits = re.sub(r"[^\d]", "", phone)
    return 10 <= len(digits) <= 15


@app.route("/")
def home():
    """Renders the main BloodConnect homepage."""
    return render_template("index.html")


@app.route("/find-blood", methods=["GET"])
def find_blood():
    """
    Search route to find blood availability by blood group, city, and units.
    Reads query parameters from the search form and queries both:
    1. Registered available community donors in SQLite (with masked contact)
    2. Demonstration blood bank stock (clearly labeled as sample data)
    """
    blood_group = request.args.get("blood_group", "").strip().upper()
    city = request.args.get("city", "").strip()
    units = request.args.get("units", "1").strip()

    has_searched = bool(blood_group or city)
    sample_results = []
    community_donors = []

    if has_searched:
        # 1. Filter sample demonstration blood banks
        for item in SAMPLE_BLOOD_BANKS:
            match_group = not blood_group or item["blood_group"] == blood_group
            match_city = not city or city.lower() in item["city"].lower()
            if match_group and match_city:
                sample_results.append(item)

        # 2. Query registered donors from SQLite
        conn = get_db()
        try:
            query = "SELECT donor_id, name, blood_group, city, phone, is_available FROM donors WHERE is_available = 1"
            params = []
            if blood_group:
                query += " AND blood_group = ?"
                params.append(blood_group)
            if city:
                query += " AND LOWER(city) LIKE LOWER(?)"
                params.append(f"%{city}%")

            rows = conn.execute(query, params).fetchall()
            for r in rows:
                community_donors.append({
                    "donor_id": r["donor_id"],
                    "name": r["name"],
                    "blood_group": r["blood_group"],
                    "city": r["city"],
                    "masked_phone": mask_phone(r["phone"]),
                })
        finally:
            conn.close()

    return render_template(
        "search.html",
        blood_group=blood_group,
        city=city,
        units=units,
        has_searched=has_searched,
        results=sample_results,
        community_donors=community_donors,
    )


@app.route("/become-donor", methods=["GET", "POST"])
def become_donor():
    """
    Donor onboarding:
    - GET: renders the registration form.
    - POST: validates required fields, enforces age/blood-group rules,
      stores in SQLite via parameterized query, and redirects to Digital ID card.
    """
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        blood_group = request.form.get("blood_group", "").strip().upper()
        age_str = request.form.get("age", "").strip()
        city = request.form.get("city", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        form_data = {
            "name": name,
            "blood_group": blood_group,
            "age": age_str,
            "city": city,
            "phone": phone,
            "email": email,
        }

        # Server-side validation
        if not name or len(name) < 2:
            return render_template("become_donor.html", error="Please provide a valid full name (at least 2 characters).", form_data=form_data)

        if blood_group not in VALID_BLOOD_GROUPS:
            return render_template("become_donor.html", error=f"Invalid blood group. Please select one of: {', '.join(sorted(list(VALID_BLOOD_GROUPS)))}", form_data=form_data)

        try:
            age = int(age_str)
            if not (18 <= age <= 65):
                return render_template("become_donor.html", error="Donor age must be between 18 and 65 years.", form_data=form_data)
        except (ValueError, TypeError):
            return render_template("become_donor.html", error="Please enter a valid numeric age between 18 and 65.", form_data=form_data)

        if not city or len(city) < 2:
            return render_template("become_donor.html", error="Please enter a valid city or campus location.", form_data=form_data)

        if not is_valid_phone(phone):
            return render_template("become_donor.html", error="Please enter a valid phone number with 10 to 15 digits.", form_data=form_data)

        if not is_valid_email(email):
            return render_template("become_donor.html", error="Please enter a valid email address.", form_data=form_data)

        if password and len(password) < 6:
            return render_template("become_donor.html", error="Account password must be at least 6 characters long.", form_data=form_data)

        try:
            donor = create_donor(
                name=name,
                blood_group=blood_group,
                age=age,
                phone=phone,
                email=email,
                city=city,
                password=password or None,
            )
            flash(f"Welcome to BloodConnect, {donor['name']}! Your donor pass has been issued.", "success")
            return redirect(url_for("donor_card", donor_id=donor["donor_id"]))
        except ValueError as e:
            return render_template("become_donor.html", error=str(e), form_data=form_data)

    return render_template("become_donor.html", form_data=None)


@app.route("/donor/card/<donor_id>")
def donor_card(donor_id: str):
    """
    Renders the Digital Donor ID card.
    Displays donor ID, name, blood group, city, registration date, and masked phone.
    Includes the QR code linking to the donor's unpredictable profile URL.
    """
    donor = get_donor_by_id(donor_id)
    if not donor:
        abort(404)

    masked_phone = mask_phone(donor["phone"])
    profile_url = get_public_url("donor_profile", token=donor["qr_token"])
    return render_template("donor_card.html", donor=donor, masked_phone=masked_phone, profile_url=profile_url)


@app.route("/donor/profile/<token>")
def donor_profile(token: str):
    """
    Public QR-scanned profile page.
    Strictly displays approved public fields only (Donor ID, Name, Blood Group, City, Status).
    Protects email, full phone number, and individual clinical donation histories.
    """
    donor = get_donor_by_token(token)
    if not donor:
        abort(404)

    return render_template("donor_profile.html", donor=donor)


@app.route("/donor/qr/<token>.png")
def donor_qr_image(token: str):
    """
    Generates and streams a PNG QR code for the donor's tokenized profile.
    The QR matrix strictly contains ONLY the profile URL.
    No personally identifiable information is embedded into the QR code.
    Ensures public HTTPS origin in production and localhost in local dev.
    """
    donor = get_donor_by_token(token)
    if not donor:
        abort(404)

    # Encode public profile verification URL into the QR code
    profile_url = get_public_url("donor_profile", token=token)
    png_bytes = generate_qr_png_bytes(profile_url)
    return Response(png_bytes, mimetype="image/png")


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Multi-role login interface.
    Uses password hashing for authentication.
    Supports Donor and authorized Hospital Staff sign-ins.
    """
    if request.method == "POST":
        role = request.form.get("role", "donor").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("login.html", error="Please enter both email and password.", role=role, email=email)

        if role == "donor":
            donor = get_donor_by_email(email)
            if not donor:
                return render_template("login.html", error="No registered donor found with this email.", role=role, email=email)

            if not donor["password_hash"]:
                # Donor registered without setting an account password
                flash("You registered without a password. Redirecting to your donor card.", "info")
                return redirect(url_for("donor_card", donor_id=donor["donor_id"]))

            if not check_password_hash(donor["password_hash"], password):
                return render_template("login.html", error="Incorrect donor password.", role=role, email=email)

            session["donor_id"] = donor["donor_id"]
            session["donor_name"] = donor["name"]
            flash(f"Welcome back, {donor['name']}!", "success")
            return redirect(url_for("donor_card", donor_id=donor["donor_id"]))

        elif role == "hospital":
            staff = get_staff_by_email(email)
            if not staff or not check_password_hash(staff["password_hash"], password):
                return render_template("login.html", error="Invalid hospital staff credentials.", role=role, email=email)

            session["is_staff"] = True
            session["staff_id"] = staff["staff_id"]
            session["staff_name"] = staff["name"]
            session["hospital_name"] = staff["hospital_name"]
            flash(f"Staff login successful: {staff['name']} ({staff['hospital_name']})", "success")
            return redirect(url_for("home"))

        elif role in ("patient", "admin"):
            flash(f"The {role.capitalize()} dashboard is scheduled for upcoming milestones. Check back soon!", "info")
            return render_template("login.html", role=role, email=email)

    return render_template("login.html")


@app.route("/logout")
def logout():
    """Clears user session and redirects to homepage."""
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("home"))


@app.route("/api/verify-donation", methods=["POST"])
def api_verify_donation():
    """
    Authorized staff API endpoint to record or verify a donation.
    Enforces authorization: unauthenticated or unauthorized users receive 403 Forbidden.
    Prevents unauthorized or invented verified donation records.
    """
    if not session.get("is_staff") or not session.get("staff_id"):
        return jsonify({"error": "Unauthorized: Hospital staff authentication required."}), 403

    data = request.get_json(silent=True) or request.form
    donor_id = data.get("donor_id", "").strip()
    hospital_name = data.get("hospital_name", session.get("hospital_name", "")).strip()
    donation_date = data.get("donation_date", "").strip()
    units = int(data.get("units", 1))

    if not donor_id or not donation_date:
        return jsonify({"error": "Missing required fields: donor_id and donation_date are mandatory."}), 400

    try:
        record = record_verified_donation(
            donor_id=donor_id,
            hospital_name=hospital_name,
            donation_date=donation_date,
            staff_id=session["staff_id"],
            units=units,
        )
        return jsonify({
            "status": "success",
            "message": "Donation verified and recorded successfully.",
            "record": record,
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/health")
def health_check():
    """
    Health check endpoint to verify that the Flask server and SQLite database are operating properly.
    """
    db_ok = False
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "app": "BloodConnect",
        "version": "1.1.0",
        "database": "connected" if db_ok else "error",
        "message": "Service is up and running",
    }), 200


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
