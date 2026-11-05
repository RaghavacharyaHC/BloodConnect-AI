"""
BloodConnect — Database Module (PostgreSQL & SQLite Dual Driver)
Handles database connections, schema creation, parameterized queries,
and data models for donors, donation records, and authorized staff.

Supports:
- Hosted PostgreSQL (e.g. Neon, Supabase, Vercel Postgres, AWS RDS) via DATABASE_URL or POSTGRES_URL
- Local SQLite fallback for seamless offline development
- Parameterized SQL execution preventing SQL injection
- Non-destructive, idempotent table initialization (CREATE TABLE IF NOT EXISTS)
"""

import os
import sqlite3
import secrets
from typing import Optional, List, Dict, Any
from werkzeug.security import generate_password_hash, check_password_hash

# Try importing psycopg2 for PostgreSQL connectivity
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bloodconnect.db")

VALID_BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}


def get_database_engine(db_path: Optional[str] = None) -> str:
    """
    Determines the active database engine.
    Returns 'postgres' if DATABASE_URL or POSTGRES_URL is configured (and db_path is None),
    otherwise returns 'sqlite'.
    """
    if db_path is not None:
        return "sqlite"
    url = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
    if url and (url.startswith("postgres://") or url.startswith("postgresql://")):
        return "postgres"
    return "sqlite"


def normalize_postgres_url(url: str) -> str:
    """
    Normalizes postgres:// scheme to postgresql:// as required by modern psycopg2/SQLAlchemy,
    and ensures sslmode is set for secure cloud connections if not specified.
    """
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "sslmode=" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}sslmode=require"
    return url


class PostgresCursorWrapper:
    """
    Cursor wrapper around psycopg2 cursor that provides uniform dict-like
    row access matching sqlite3.Row behavior.
    """
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self) -> Optional[Dict[str, Any]]:
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> List[Dict[str, Any]]:
        rows = self.cursor.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        return getattr(self.cursor, "lastrowid", None)

    def __iter__(self):
        for row in self.cursor:
            yield dict(row)

    def close(self):
        self.cursor.close()


class DatabaseConnection:
    """
    Unified database connection wrapper providing identical interface
    over both SQLite (local development) and PostgreSQL (hosted/Vercel).
    """
    def __init__(self, raw_conn, engine_type: str = "sqlite"):
        self.raw_conn = raw_conn
        self.engine_type = engine_type

    def execute(self, sql: str, params=None):
        params = params or ()
        if self.engine_type == "postgres":
            # Convert standard '?' qmark placeholders to '%s' pyformat placeholders
            pg_sql = sql.replace("?", "%s")
            cursor = self.raw_conn.cursor()
            cursor.execute(pg_sql, params)
            return PostgresCursorWrapper(cursor)
        else:
            return self.raw_conn.execute(sql, params)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def get_db(db_path: Optional[str] = None) -> DatabaseConnection:
    """
    Returns an open, unified DatabaseConnection (PostgreSQL or SQLite).
    """
    engine = get_database_engine(db_path)

    if engine == "postgres":
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError(
                "PostgreSQL DATABASE_URL is configured, but 'psycopg2-binary' is not installed. "
                "Run: pip install psycopg2-binary"
            )
        raw_url = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
        dsn = normalize_postgres_url(raw_url)
        raw_conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)
        return DatabaseConnection(raw_conn, engine_type="postgres")
    else:
        path = db_path or os.environ.get("BLOODCONNECT_DB", DEFAULT_DB_PATH)
        raw_conn = sqlite3.connect(path)
        raw_conn.row_factory = sqlite3.Row
        raw_conn.execute("PRAGMA foreign_keys = ON;")
        return DatabaseConnection(raw_conn, engine_type="sqlite")


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes database tables safely and idempotently.
    Uses CREATE TABLE IF NOT EXISTS to guarantee that existing data is NEVER deleted.
    """
    engine = get_database_engine(db_path)
    conn = get_db(db_path)

    with conn:
        if engine == "postgres":
            # PostgreSQL schema definition
            conn.execute("""
                CREATE TABLE IF NOT EXISTS donors (
                    id SERIAL PRIMARY KEY,
                    donor_id VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    blood_group VARCHAR(10) NOT NULL,
                    age INTEGER NOT NULL,
                    gender VARCHAR(50),
                    phone VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    city VARCHAR(255) NOT NULL,
                    qr_token VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255),
                    is_available INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS donation_history (
                    id SERIAL PRIMARY KEY,
                    donor_id VARCHAR(50) NOT NULL REFERENCES donors(donor_id) ON DELETE CASCADE,
                    donation_date VARCHAR(50) NOT NULL,
                    hospital_name VARCHAR(255) NOT NULL,
                    units INTEGER DEFAULT 1,
                    is_verified INTEGER DEFAULT 0,
                    verified_by_staff_id VARCHAR(50),
                    verified_at VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS staff_users (
                    id SERIAL PRIMARY KEY,
                    staff_id VARCHAR(50) UNIQUE NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    hospital_name VARCHAR(255) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) DEFAULT 'staff',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            # SQLite schema definition
            conn.execute("""
                CREATE TABLE IF NOT EXISTS donors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    donor_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    blood_group TEXT NOT NULL,
                    age INTEGER NOT NULL,
                    gender TEXT,
                    phone TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    city TEXT NOT NULL,
                    qr_token TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    is_available INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS donation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    donor_id TEXT NOT NULL,
                    donation_date TEXT NOT NULL,
                    hospital_name TEXT NOT NULL,
                    units INTEGER DEFAULT 1,
                    is_verified INTEGER DEFAULT 0,
                    verified_by_staff_id TEXT,
                    verified_at TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (donor_id) REFERENCES donors(donor_id) ON DELETE CASCADE
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS staff_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    staff_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    hospital_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'staff',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    conn.close()


def generate_unique_donor_id(conn: DatabaseConnection) -> str:
    """
    Generates a unique, professional donor ID in the format BC-YYYY-XXXX.
    Ensures collision-free assignment.
    """
    for _ in range(20):
        random_suffix = secrets.token_hex(2).upper()  # 4 hex characters
        candidate_id = f"BC-2026-{random_suffix}"
        row = conn.execute("SELECT 1 FROM donors WHERE donor_id = ?", (candidate_id,)).fetchone()
        if not row:
            return candidate_id
    # Fallback to high-entropy token
    return f"BC-2026-{secrets.token_hex(4).upper()}"


def generate_qr_token() -> str:
    """
    Generates an unguessable 256-bit URL-safe token for the donor's QR profile link.
    Personal data is NEVER embedded directly into the QR code.
    """
    return secrets.token_urlsafe(32)


def mask_phone(phone: Optional[str]) -> str:
    """
    Masks a phone number for privacy on public or semi-public pages.
    Example: '+91 9876543210' -> '+91 98*****210'
             '9876543210'     -> '98*****210'
    """
    if not phone:
        return "Protected"
    cleaned = phone.strip()
    if len(cleaned) <= 5:
        return "***"
    prefix = cleaned[:4]
    suffix = cleaned[-3:]
    return f"{prefix}*****{suffix}"


def create_donor(
    name: str,
    blood_group: str,
    age: int,
    phone: str,
    email: str,
    city: str,
    gender: str = "Unspecified",
    password: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Registers a new donor using parameterized queries.
    Validates constraints and returns the created donor dictionary.
    """
    blood_group = blood_group.strip().upper()
    if blood_group not in VALID_BLOOD_GROUPS:
        raise ValueError(f"Invalid blood group: '{blood_group}'. Must be one of {sorted(list(VALID_BLOOD_GROUPS))}")

    if not (18 <= age <= 65):
        raise ValueError("Donor age must be between 18 and 65 years for medical eligibility.")

    name = name.strip()
    if len(name) < 2:
        raise ValueError("Donor name must be at least 2 characters long.")

    city = city.strip()
    if len(city) < 2:
        raise ValueError("City name must be at least 2 characters long.")

    phone = phone.strip()
    email = email.strip().lower()

    password_hash = generate_password_hash(password) if password else None
    qr_token = generate_qr_token()

    conn = get_db(db_path)
    try:
        with conn:
            # Check duplicate email
            existing_email = conn.execute("SELECT donor_id FROM donors WHERE email = ?", (email,)).fetchone()
            if existing_email:
                raise ValueError("A donor with this email address is already registered.")

            # Check duplicate phone
            existing_phone = conn.execute("SELECT donor_id FROM donors WHERE phone = ?", (phone,)).fetchone()
            if existing_phone:
                raise ValueError("A donor with this phone number is already registered.")

            donor_id = generate_unique_donor_id(conn)

            conn.execute(
                """
                INSERT INTO donors (
                    donor_id, name, blood_group, age, gender, phone, email,
                    city, qr_token, password_hash, is_available
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (donor_id, name, blood_group, age, gender, phone, email, city, qr_token, password_hash),
            )

        row = conn.execute("SELECT * FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_donor_by_id(donor_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a donor by unique donor ID."""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT * FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_donor_by_token(qr_token: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a donor by unpredictable QR token."""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT * FROM donors WHERE qr_token = ?", (qr_token,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_donor_by_email(email: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a donor by email for authentication."""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT * FROM donors WHERE LOWER(email) = LOWER(?)", (email.strip(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_donor_donations(donor_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves donation history for a donor."""
    conn = get_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM donation_history
            WHERE donor_id = ?
            ORDER BY donation_date DESC, id DESC
            """,
            (donor_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_staff_user(
    staff_id: str,
    name: str,
    email: str,
    hospital_name: str,
    password: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates an authorized hospital/blood-bank staff member with a securely hashed password.
    Safe across PostgreSQL and SQLite using standard ON CONFLICT (staff_id) DO UPDATE.
    """
    email = email.strip().lower()
    pw_hash = generate_password_hash(password)
    conn = get_db(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO staff_users (staff_id, name, email, hospital_name, password_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (staff_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    hospital_name = EXCLUDED.hospital_name,
                    password_hash = EXCLUDED.password_hash
                """,
                (staff_id.strip(), name.strip(), email, hospital_name.strip(), pw_hash),
            )
        row = conn.execute("SELECT * FROM staff_users WHERE staff_id = ?", (staff_id.strip(),)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_staff_by_email(email: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves staff member by email for authentication."""
    conn = get_db(db_path)
    try:
        row = conn.execute("SELECT * FROM staff_users WHERE LOWER(email) = LOWER(?)", (email.strip(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_verified_donation(
    donor_id: str,
    hospital_name: str,
    donation_date: str,
    staff_id: str,
    units: int = 1,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Records a verified donation. Can ONLY be executed with valid staff identification.
    Uses RETURNING id for universal compatibility between PostgreSQL and modern SQLite.
    """
    conn = get_db(db_path)
    try:
        with conn:
            # Check donor exists
            donor = conn.execute("SELECT donor_id FROM donors WHERE donor_id = ?", (donor_id,)).fetchone()
            if not donor:
                raise ValueError(f"Donor '{donor_id}' not found.")

            # Check staff exists
            staff = conn.execute("SELECT staff_id FROM staff_users WHERE staff_id = ?", (staff_id,)).fetchone()
            if not staff:
                raise ValueError("Unauthorized: Staff ID not recognized.")

            cursor = conn.execute(
                """
                INSERT INTO donation_history (
                    donor_id, donation_date, hospital_name, units,
                    is_verified, verified_by_staff_id, verified_at
                ) VALUES (?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (donor_id, donation_date, hospital_name, units, staff_id),
            )
            inserted_row = cursor.fetchone()
            inserted_id = inserted_row["id"] if inserted_row else cursor.lastrowid

        row = conn.execute("SELECT * FROM donation_history WHERE id = ?", (inserted_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()
