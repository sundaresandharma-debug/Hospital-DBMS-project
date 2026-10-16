import functools
import html
import json
import os
import sqlite3
from datetime import datetime
from flask import Flask, Response, jsonify, request, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db, init_db
from email_utils import read_unsubscribe_token


def env_flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


# DEMO_MODE seeds fictional sample data, shows demo logins and enables the reset button.
# It must be turned off (DEMO_MODE=0) before real patients use the portal.
DEMO_MODE = env_flag("DEMO_MODE", "1")
# Staff accounts can only be self-registered with this code; empty disables staff sign-up.
STAFF_INVITE_CODE = os.environ.get("STAFF_INVITE_CODE", "")
# Version of the Terms / Privacy Policy users accept at sign-up (bump when the documents change).
POLICY_VERSION = "2026-10-16"
# The single consultation fee shown to and charged to patients; no other fees are added.
CONSULTATION_FEE = float(os.environ.get("CONSULTATION_FEE", "800"))
ADULT_AGE = 18

# Legal entity details displayed in the footer, legal pages and printed slips.
# Placeholders in [brackets] must be replaced with the operator's real details before launch.
BUSINESS = {
    "name": os.environ.get("BUSINESS_NAME", "[Registered legal entity name]"),
    "trading_name": os.environ.get("BUSINESS_TRADING_NAME", "PulseCare+"),
    "address": os.environ.get("BUSINESS_ADDRESS", "[Registered office address]"),
    "registration": os.environ.get("BUSINESS_REGISTRATION", "[Company / hospital registration number]"),
    "tax_id": os.environ.get("BUSINESS_TAX_ID", "[GSTIN / tax ID]"),
    "email": os.environ.get("BUSINESS_EMAIL", "[support email]"),
    "privacy_email": os.environ.get("BUSINESS_PRIVACY_EMAIL", "[privacy / grievance officer email]"),
    "grievance_officer": os.environ.get("BUSINESS_GRIEVANCE_OFFICER", "[Grievance / data protection officer name]"),
    "phone": os.environ.get("BUSINESS_PHONE", "[contact phone]"),
}

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "hnm-hospital-vibrant-secret-key-2026")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL")) or env_flag("SESSION_COOKIE_SECURE", "0")


# Initialize database schema (and demo data only in demo mode) on startup
with app.app_context():
    init_db(demo_mode=DEMO_MODE)


# Only same-origin resources are allowed: fonts and icons are self-hosted under
# /vendor, so no visitor data is sent to third-party CDNs or trackers.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.after_request
def set_security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def current_patient_ids(cursor):
    cursor.execute(
        "SELECT PID FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)",
        (session["user"], session["user"]),
    )
    return {row["PID"] for row in cursor.fetchall()}


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if "user" not in session:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        return view(**kwargs)
    return wrapped_view


def staff_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if "user" not in session:
            return jsonify({"error": "Authentication required."}), 401
        if session.get("role") != "staff":
            return jsonify({"error": "Access denied. Staff permission required."}), 403
        return view(**kwargs)
    return wrapped_view


# Static file routes for Single Page Application
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


LEGAL_PAGES = {
    "privacy": "privacy.html",
    "terms": "terms.html",
    "refunds": "refunds.html",
    "cookies": "cookies.html",
    "accessibility": "accessibility.html",
}


@app.route("/<any(privacy, terms, refunds, cookies, accessibility):page>")
def legal_page(page):
    return send_from_directory(os.path.join("static", "legal"), LEGAL_PAGES[page])


@app.route("/<path:path>")
def static_proxy(path):
    if os.path.exists(os.path.join("static", path)):
        return send_from_directory("static", path)
    return send_from_directory("static", "index.html")


# ================= PUBLIC SITE INFO (BUSINESS DETAILS & FLAGS) =================

@app.route("/api/site-info", methods=["GET"])
def site_info():
    return jsonify({
        "business": BUSINESS,
        "demo_mode": DEMO_MODE,
        "staff_signup_enabled": bool(STAFF_INVITE_CODE),
        "consultation_fee": CONSULTATION_FEE,
        "policy_version": POLICY_VERSION,
        "adult_age": ADULT_AGE,
    })


# ================= AUTHENTICATION (EXPLICIT ERROR PROMPTS) =================

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "patient").strip().lower()
    name = (data.get("name") or "").strip()
    mobile = (data.get("mobile_no") or "").strip()
    accepted_terms = data.get("accept_terms") is True
    health_consent = data.get("health_data_consent") is True
    marketing_opt_in = 1 if data.get("marketing_opt_in") is True else 0
    age_group = data.get("age_group")
    guardian_name = (data.get("guardian_name") or "").strip()
    guardian_consent = data.get("guardian_consent") is True

    if not username or len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters long"}), 400
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400
    if role not in ["staff", "patient"]:
        return jsonify({"error": "Role must be either 'staff' or 'patient'"}), 400
    if role == "staff":
        if not STAFF_INVITE_CODE:
            return jsonify({"error": "Staff self-registration is disabled. Ask your hospital administrator for an account."}), 403
        if (data.get("staff_invite_code") or "") != STAFF_INVITE_CODE:
            return jsonify({"error": "Invalid staff invite code."}), 403
    if not accepted_terms:
        return jsonify({"error": "You must accept the Terms of Service and Privacy Policy to create an account."}), 400
    if age_group not in ("adult", "minor"):
        return jsonify({"error": f"Please confirm whether the patient is {ADULT_AGE} or older."}), 400
    if age_group == "minor":
        if role == "staff":
            return jsonify({"error": f"Staff accounts are only available to people aged {ADULT_AGE} or older."}), 400
        if not guardian_name or not guardian_consent:
            return jsonify({"error": f"For patients under {ADULT_AGE}, a parent or legal guardian must give consent and enter their name."}), 400
    if role == "patient" and not health_consent:
        return jsonify({"error": "Explicit consent to process health information is required to use patient services."}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Check if account already exists
    cursor.execute("SELECT USERNAME FROM USER_DATA WHERE USERNAME = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "Account already exists. Please login."}), 409

    hashed_pw = generate_password_hash(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_minor = 1 if age_group == "minor" else 0
    cursor.execute(
        """INSERT INTO USER_DATA (
            USERNAME, PASSWORD, ROLE, NAME, MOBILE_NO, TERMS_ACCEPTED_AT, POLICY_VERSION,
            HEALTH_DATA_CONSENT_AT, MARKETING_OPT_IN, IS_MINOR, GUARDIAN_NAME, GUARDIAN_CONSENT_AT
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            username, hashed_pw, role, name or username.capitalize(), mobile, now, POLICY_VERSION,
            now if health_consent else None, marketing_opt_in, is_minor,
            guardian_name if is_minor else None, now if is_minor else None,
        ),
    )

    # Automatically create/link patient record if registered as a patient.
    # Age and gender are left empty until the patient provides them (no invented values).
    if role == "patient":
        cursor.execute("SELECT COUNT(*) FROM PATIENTS")
        count = cursor.fetchone()[0] + 1
        pid = f"PAT{count:03d}"
        bill_no = f"BILL-{1000 + count}"
        cursor.execute(
            """INSERT INTO PATIENTS (
                PID, NAME, ISSUE, AGE, GENDER, FEES, MOBILE_NO, BILL_NO, USERNAME,
                BLOOD_GROUP, ALLERGIES, MEDICAL_HISTORY, GUARDIAN_NAME
            ) VALUES (?, ?, ?, NULL, NULL, 0, ?, ?, ?, 'Unknown', NULL, NULL, ?)""",
            (pid, name or username.capitalize(), None, mobile, bill_no, username, guardian_name if is_minor else None),
        )

    conn.commit()
    conn.close()

    session["user"] = username
    session["role"] = role
    session["name"] = name or username.capitalize()

    return jsonify({
        "message": f"Account successfully created as {role.upper()}!",
        "user": {
            "username": username,
            "role": role,
            "name": name or username.capitalize()
        }
    }), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "Please enter both username and password"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT USERNAME, PASSWORD, ROLE, NAME, MOBILE_NO FROM USER_DATA WHERE USERNAME = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    # Check if account does not exist
    if not row:
        return jsonify({"error": "Account does not exist. Please register."}), 404

    # Check password match
    if not check_password_hash(row["PASSWORD"], password):
        return jsonify({"error": "Incorrect password. Please try again."}), 401

    session["user"] = row["USERNAME"]
    session["role"] = row["ROLE"]
    session["name"] = row["NAME"] or row["USERNAME"]

    return jsonify({
        "message": "Login successful",
        "user": {
            "username": row["USERNAME"],
            "role": row["ROLE"],
            "name": row["NAME"] or row["USERNAME"],
            "mobile_no": row["MOBILE_NO"]
        }
    })


@app.route("/api/auth/me", methods=["GET"])
def get_current_user():
    if "user" not in session:
        return jsonify({"authenticated": False}), 200

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT USERNAME, ROLE, NAME, MOBILE_NO, MARKETING_OPT_IN FROM USER_DATA WHERE USERNAME = ?", (session["user"],))
    user_row = cursor.fetchone()

    patient_profile = None
    if user_row and user_row["ROLE"] == "patient":
        cursor.execute("SELECT * FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = ?", (user_row["USERNAME"], user_row["MOBILE_NO"]))
        p_row = cursor.fetchone()
        if p_row:
            patient_profile = dict(p_row)

    conn.close()

    if not user_row:
        session.clear()
        return jsonify({"authenticated": False}), 200

    return jsonify({
        "authenticated": True,
        "user": {
            "username": user_row["USERNAME"],
            "role": user_row["ROLE"],
            "name": user_row["NAME"] or user_row["USERNAME"],
            "mobile_no": user_row["MOBILE_NO"],
            "marketing_opt_in": bool(user_row["MARKETING_OPT_IN"]),
            "patient_profile": patient_profile
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})


# ================= DASHBOARD METRICS (ROLE-BASED APPOINTMENT COUNTS) =================

@app.route("/api/dashboard/stats", methods=["GET"])
@login_required
def get_stats():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM EMPLOYEES")
    employees_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM PATIENTS")
    patients_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM EMT WHERE VNO IN (SELECT VNO FROM EMT_STATUS WHERE STATUS = 'Available')")
    available_ambulances = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM PHARMACY WHERE STOCK < 50")
    low_stock_medicines = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM BEDS WHERE STATUS = 'Available'")
    available_beds = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM BEDS WHERE STATUS = 'Occupied'")
    occupied_beds = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM BEDS")
    total_beds = cursor.fetchone()[0]

    # Appointments Count: Hospital-wide for Staff vs. Patient's own for Patient
    user_role = session.get("role")
    if user_role == "patient":
        cursor.execute(
            """SELECT COUNT(*) FROM CONSULTATION C
               JOIN PATIENTS P ON C.PATIENT_ID = P.PID
               WHERE (P.USERNAME = ? OR P.MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?))
               AND C.STATUS = 'Scheduled'""",
            (session["user"], session["user"]),
        )
        scheduled_consultations = cursor.fetchone()[0]
    else:
        cursor.execute("SELECT COUNT(*) FROM CONSULTATION WHERE STATUS = 'Scheduled'")
        scheduled_consultations = cursor.fetchone()[0]

    conn.close()

    return jsonify({
        "employees": employees_count,
        "patients": patients_count,
        "available_ambulances": available_ambulances,
        "low_stock_medicines": low_stock_medicines,
        "scheduled_consultations": scheduled_consultations,
        "available_beds": available_beds,
        "occupied_beds": occupied_beds,
        "total_beds": total_beds,
        "current_user_role": user_role
    })


# ================= HOSPITAL WARD BEDS (STRICT 1-BED LIMIT & ADMIN CONTROLS) =================

@app.route("/api/beds", methods=["GET"])
@login_required
def get_beds():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT B.BED_ID, B.WARD_TYPE, B.BED_NUMBER, B.STATUS, B.PATIENT_ID, B.ASSIGNED_DATE,
               P.NAME AS PATIENT_NAME, P.AGE AS PATIENT_AGE, P.GENDER AS PATIENT_GENDER,
               P.ISSUE AS PATIENT_ISSUE, P.BILL_NO, P.MOBILE_NO, P.BLOOD_GROUP, P.ALLERGIES
        FROM BEDS B
        LEFT JOIN PATIENTS P ON B.PATIENT_ID = P.PID
        ORDER BY B.WARD_TYPE ASC, B.BED_ID ASC
    """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    # Patients only see occupancy for other people's beds, never their identity or health details.
    if session.get("role") != "staff":
        own_ids = current_patient_ids(cursor)
        patient_fields = ["PATIENT_ID", "PATIENT_NAME", "PATIENT_AGE", "PATIENT_GENDER", "PATIENT_ISSUE",
                          "BILL_NO", "MOBILE_NO", "BLOOD_GROUP", "ALLERGIES", "ASSIGNED_DATE"]
        for row in rows:
            row["IS_MINE"] = row["PATIENT_ID"] in own_ids
            if not row["IS_MINE"]:
                for field in patient_fields:
                    row[field] = None

    conn.close()
    return jsonify(rows)


# Patient Direct Bed Booking (Enforces 1 Bed per Patient Rule)
@app.route("/api/beds/book", methods=["POST"])
@login_required
def book_bed():
    data = request.get_json() or {}
    bed_id = data.get("BED_ID")
    assigned_date = datetime.now().strftime("%Y-%m-%d")

    if not bed_id:
        return jsonify({"error": "Bed ID is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Retrieve patient record linked to current user
    cursor.execute("SELECT PID, NAME FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)", (session["user"], session["user"]))
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return jsonify({"error": "No patient record found for your account. Please complete your health profile."}), 400

    patient_id = patient["PID"]
    patient_name = patient["NAME"]

    # Check: Does the patient already have an active bed reserved?
    cursor.execute("SELECT BED_ID, WARD_TYPE, BED_NUMBER FROM BEDS WHERE PATIENT_ID = ? AND STATUS = 'Occupied'", (patient_id,))
    existing_bed = cursor.fetchone()
    if existing_bed:
        conn.close()
        return jsonify({
            "error": f"You already have an active bed reserved (Bed {existing_bed['BED_NUMBER']} in {existing_bed['WARD_TYPE']}). You can only book one bed at a time until you are recovered and discharged."
        }), 400

    # Verify target bed is available
    cursor.execute("SELECT STATUS, WARD_TYPE, BED_NUMBER FROM BEDS WHERE BED_ID = ?", (bed_id,))
    bed = cursor.fetchone()
    if not bed:
        conn.close()
        return jsonify({"error": "Selected bed does not exist"}), 404
    if bed["STATUS"] != "Available":
        conn.close()
        return jsonify({"error": f"Bed {bed['BED_NUMBER']} is currently {bed['STATUS'].lower()} and cannot be reserved."}), 409

    # Book the bed
    cursor.execute(
        "UPDATE BEDS SET STATUS = 'Occupied', PATIENT_ID = ?, ASSIGNED_DATE = ? WHERE BED_ID = ?",
        (patient_id, assigned_date, bed_id),
    )

    alert_msg = f"Patient {patient_name} reserved Bed {bed['BED_NUMBER']} in {bed['WARD_TYPE']}."
    cursor.execute("INSERT INTO NOTIFICATIONS (TYPE, MESSAGE) VALUES ('bed', ?)", (alert_msg,))

    conn.commit()
    conn.close()
    return jsonify({"message": f"Successfully reserved Bed {bed['BED_NUMBER']} ({bed['WARD_TYPE']})!"})


# Staff: Allocate or Reassign Bed
@app.route("/api/beds/assign", methods=["POST"])
@staff_required
def assign_bed():
    data = request.get_json() or {}
    bed_id = data.get("BED_ID")
    patient_id = data.get("PATIENT_ID")
    assigned_date = datetime.now().strftime("%Y-%m-%d")

    if not bed_id or not patient_id:
        return jsonify({"error": "Both Bed ID and Patient ID are required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT NAME FROM PATIENTS WHERE PID = ?", (patient_id,))
    patient = cursor.fetchone()
    if not patient:
        conn.close()
        return jsonify({"error": f"Patient with ID {patient_id} does not exist"}), 404

    # Remove any existing bed occupation for this patient to maintain 1-bed policy
    cursor.execute("UPDATE BEDS SET STATUS = 'Available', PATIENT_ID = NULL, ASSIGNED_DATE = NULL WHERE PATIENT_ID = ?", (patient_id,))

    cursor.execute(
        "UPDATE BEDS SET STATUS = 'Occupied', PATIENT_ID = ?, ASSIGNED_DATE = ? WHERE BED_ID = ?",
        (patient_id, assigned_date, bed_id),
    )

    alert_msg = f"Staff allocated Bed {bed_id} to Patient {patient['NAME']}."
    cursor.execute("INSERT INTO NOTIFICATIONS (TYPE, MESSAGE) VALUES ('bed', ?)", (alert_msg,))

    conn.commit()
    conn.close()
    return jsonify({"message": f"Bed {bed_id} successfully allocated to {patient['NAME']}"})


# Staff: Discharge Bed / Remove Reservation
@app.route("/api/beds/vacate", methods=["POST"])
@staff_required
def vacate_bed():
    data = request.get_json() or {}
    bed_id = data.get("BED_ID")

    if not bed_id:
        return jsonify({"error": "Bed ID is required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE BEDS SET STATUS = 'Available', PATIENT_ID = NULL, ASSIGNED_DATE = NULL WHERE BED_ID = ?",
        (bed_id,),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": f"Bed {bed_id} discharged and marked Available"})


# Staff: Toggle Bed Maintenance / Available Status
@app.route("/api/beds/<bed_id>/status", methods=["PATCH"])
@staff_required
def set_bed_status(bed_id):
    data = request.get_json() or {}
    new_status = data.get("STATUS")
    if new_status not in ["Available", "Maintenance"]:
        return jsonify({"error": "Status can only be set to Available or Maintenance"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE BEDS SET STATUS = ?, PATIENT_ID = NULL, ASSIGNED_DATE = NULL WHERE BED_ID = ?",
        (new_status, bed_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": f"Bed {bed_id} status updated to {new_status}"})


# ================= PHARMACY & PURCHASE HISTORY =================

@app.route("/api/pharmacy", methods=["GET"])
@login_required
def get_pharmacy():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PHARMACY ORDER BY MEDICINE_NAME ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


# Patient Medicine Purchase
@app.route("/api/pharmacy/buy", methods=["POST"])
@login_required
def buy_medicine():
    data = request.get_json() or {}
    medicine_name = (data.get("MEDICINE_NAME") or "").strip()
    quantity = int(data.get("QUANTITY", 1))

    if not medicine_name or quantity < 1:
        return jsonify({"error": "Please provide a valid medicine name and quantity (minimum 1)."}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT MEDICINE_NAME, STOCK, PRICE FROM PHARMACY WHERE MEDICINE_NAME = ?", (medicine_name,))
    med = cursor.fetchone()
    if not med:
        conn.close()
        return jsonify({"error": f"Medicine '{medicine_name}' not found."}), 404

    # Stock limit validation
    if quantity > med["STOCK"]:
        conn.close()
        return jsonify({
            "error": f"Requested quantity ({quantity} units) exceeds available stock ({med['STOCK']} units)."
        }), 400

    # Retrieve patient information
    cursor.execute("SELECT PID, NAME FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)", (session["user"], session["user"]))
    p_row = cursor.fetchone()
    patient_id = p_row["PID"] if p_row else "PAT-WALKIN"
    patient_name = p_row["NAME"] if p_row else session.get("name", "Online Patient")

    total_price = med["PRICE"] * quantity
    new_stock = med["STOCK"] - quantity
    purchase_date = datetime.now().strftime("%Y-%m-%d %H:%M")

    cursor.execute("SELECT COUNT(*) FROM MEDICINE_PURCHASES")
    order_num = cursor.fetchone()[0] + 1001
    purchase_id = f"ORD-{order_num}"

    # Decrement Pharmacy Stock
    cursor.execute("UPDATE PHARMACY SET STOCK = ? WHERE MEDICINE_NAME = ?", (new_stock, medicine_name))

    # Record in Medicine Purchase History
    cursor.execute(
        """INSERT INTO MEDICINE_PURCHASES (
            PURCHASE_ID, PATIENT_ID, PATIENT_NAME, MEDICINE_NAME, QUANTITY, TOTAL_PRICE, PURCHASE_DATE, USERNAME
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (purchase_id, patient_id, patient_name, medicine_name, quantity, total_price, purchase_date, session["user"]),
    )

    alert_msg = f"Order: Patient {patient_name} purchased {quantity} unit(s) of {medicine_name} (Total: ₹{total_price:.2f})."
    cursor.execute("INSERT INTO NOTIFICATIONS (TYPE, MESSAGE) VALUES ('pharmacy', ?)", (alert_msg,))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Successfully purchased {quantity} unit(s) of {medicine_name} for ₹{total_price:.2f}!",
        "order_id": purchase_id,
        "total_price": total_price,
        "remaining_stock": new_stock
    })


# Get Medicine Purchase History (Patient sees their own; Staff sees all)
@app.route("/api/pharmacy/purchases", methods=["GET"])
@login_required
def get_purchase_history():
    conn = get_db()
    cursor = conn.cursor()

    if session.get("role") == "patient":
        cursor.execute(
            """SELECT * FROM MEDICINE_PURCHASES 
               WHERE USERNAME = ? OR PATIENT_ID = (SELECT PID FROM PATIENTS WHERE USERNAME = ?)
               ORDER BY PURCHASE_DATE DESC""",
            (session["user"], session["user"]),
        )
    else:
        cursor.execute("SELECT * FROM MEDICINE_PURCHASES ORDER BY PURCHASE_DATE DESC")

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/pharmacy", methods=["POST"])
@staff_required
def add_medicine():
    data = request.get_json() or {}
    name = data.get("MEDICINE_NAME", "").strip()
    mtype = data.get("MEDICINE_TYPE", "").strip()
    stock = int(data.get("STOCK", 0))
    price = float(data.get("PRICE", 0.0))

    if not name or not mtype:
        return jsonify({"error": "Medicine Name and Type are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO PHARMACY (MEDICINE_NAME, MEDICINE_TYPE, STOCK, PRICE) VALUES (?, ?, ?, ?)",
            (name, mtype, stock, price),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Medicine {name} already exists. Update stock instead."}), 409

    conn.close()
    return jsonify({"message": f"Medicine {name} added to pharmacy inventory"}), 201


@app.route("/api/pharmacy/<medicine_name>", methods=["PATCH"])
@staff_required
def update_stock(medicine_name):
    data = request.get_json() or {}
    stock = data.get("STOCK")
    price = data.get("PRICE")

    conn = get_db()
    cursor = conn.cursor()
    if stock is not None:
        cursor.execute("UPDATE PHARMACY SET STOCK = ? WHERE MEDICINE_NAME = ?", (int(stock), medicine_name))
    if price is not None:
        cursor.execute("UPDATE PHARMACY SET PRICE = ? WHERE MEDICINE_NAME = ?", (float(price), medicine_name))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Updated {medicine_name}"})


# ================= PATIENT PROFILE & MEDICAL DETAILS (VIEW & UPDATE) =================

@app.route("/api/patient/profile", methods=["GET"])
@login_required
def get_patient_profile():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT P.*, B.BED_NUMBER, B.WARD_TYPE
           FROM PATIENTS P
           LEFT JOIN BEDS B ON P.PID = B.PATIENT_ID AND B.STATUS = 'Occupied'
           WHERE P.USERNAME = ? OR P.MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)""",
        (session["user"], session["user"]),
    )
    profile = cursor.fetchone()
    conn.close()

    if not profile:
        return jsonify({"error": "Patient profile not found"}), 404
    return jsonify(dict(profile))


@app.route("/api/patient/profile", methods=["PUT"])
@login_required
def update_patient_profile():
    data = request.get_json() or {}
    name = (data.get("NAME") or "").strip()
    age = data.get("AGE")
    gender = data.get("GENDER")
    mobile = (data.get("MOBILE_NO") or "").strip()
    issue = (data.get("ISSUE") or "").strip()
    blood_group = (data.get("BLOOD_GROUP") or "Unknown").strip()
    allergies = (data.get("ALLERGIES") or "None reported").strip()
    med_history = (data.get("MEDICAL_HISTORY") or "No prior chronic conditions").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Update patient clinical record
    cursor.execute(
        """UPDATE PATIENTS
           SET NAME = ?, AGE = ?, GENDER = ?, MOBILE_NO = ?, ISSUE = ?,
               BLOOD_GROUP = ?, ALLERGIES = ?, MEDICAL_HISTORY = ?
           WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)""",
        (name, age, gender, mobile, issue, blood_group, allergies, med_history, session["user"], session["user"]),
    )

    # Sync User Account Name and Contact
    cursor.execute("UPDATE USER_DATA SET NAME = ?, MOBILE_NO = ? WHERE USERNAME = ?", (name, mobile, session["user"]))
    session["name"] = name

    conn.commit()
    conn.close()

    return jsonify({"message": "Personal and medical details successfully updated!"})


# ================= EMPLOYEES (DOCTORS & STAFF) =================

@app.route("/api/employees", methods=["GET"])
@login_required
def get_employees():
    conn = get_db()
    cursor = conn.cursor()
    if session.get("role") == "staff":
        cursor.execute("SELECT * FROM EMPLOYEES ORDER BY EID ASC")
    else:
        # Patients only need to know who they can book with, not salaries or personal phone numbers.
        cursor.execute("SELECT EID, NAME, DEPARTMENT FROM EMPLOYEES ORDER BY EID ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/employees", methods=["POST"])
@staff_required
def add_employee():
    data = request.get_json() or {}
    eid = data.get("EID", "").strip().upper()
    name = data.get("NAME", "").strip()
    dept = data.get("DEPARTMENT", "").strip()
    age = data.get("AGE")
    gender = data.get("GENDER", "").strip()
    salary = data.get("SALARY", 0.0)
    mobile = data.get("MOBILE_NO", "").strip()

    if not eid or not name or not dept:
        return jsonify({"error": "EID, Name, and Department are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO EMPLOYEES (EID, NAME, DEPARTMENT, AGE, GENDER, SALARY, MOBILE_NO) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (eid, name, dept, age, gender, salary, mobile),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Doctor ID {eid} already exists"}), 409

    conn.close()
    return jsonify({"message": f"Doctor {name} added successfully", "EID": eid}), 201


@app.route("/api/employees/<eid>", methods=["DELETE"])
@staff_required
def delete_employee(eid):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM CONSULTATION WHERE EMP_ID = ?", (eid,))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return jsonify({"error": "Cannot delete doctor with active consultations"}), 400

    cursor.execute("DELETE FROM EMPLOYEES WHERE EID = ?", (eid,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Doctor/Staff {eid} removed successfully"})


# ================= PATIENTS (DOCTOR / STAFF VIEW) =================

@app.route("/api/patients", methods=["GET"])
@login_required
def get_patients():
    conn = get_db()
    cursor = conn.cursor()

    if session.get("role") == "patient":
        cursor.execute(
            "SELECT * FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)",
            (session["user"], session["user"]),
        )
    else:
        cursor.execute(
            """SELECT P.*, B.BED_NUMBER, B.WARD_TYPE
               FROM PATIENTS P
               LEFT JOIN BEDS B ON P.PID = B.PATIENT_ID AND B.STATUS = 'Occupied'
               ORDER BY P.PID ASC"""
        )

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/patients", methods=["POST"])
@staff_required
def add_patient():
    data = request.get_json() or {}
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM PATIENTS")
    next_idx = cursor.fetchone()[0] + 1
    pid = data.get("PID") or f"PAT{next_idx:03d}"
    bill_no = data.get("BILL_NO") or f"BILL-{1000 + next_idx}"
    name = data.get("NAME", "").strip()
    issue = data.get("ISSUE", "").strip()
    age = data.get("AGE")
    gender = data.get("GENDER", "Not Specified")
    fees = data.get("FEES", 0.0)
    mobile = data.get("MOBILE_NO", "").strip()
    blood_group = data.get("BLOOD_GROUP", "Unknown")
    allergies = data.get("ALLERGIES", "None reported")
    med_history = data.get("MEDICAL_HISTORY", "No prior chronic conditions")
    username = data.get("USERNAME")
    guardian_name = (data.get("GUARDIAN_NAME") or "").strip() or None

    if not name:
        conn.close()
        return jsonify({"error": "Patient name is required"}), 400
    try:
        is_minor = age is not None and int(age) < ADULT_AGE
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"error": "Age must be a number"}), 400
    if is_minor and not guardian_name:
        conn.close()
        return jsonify({"error": f"Patients under {ADULT_AGE} need a parent or legal guardian recorded as consenting."}), 400

    try:
        cursor.execute(
            """INSERT INTO PATIENTS (
                PID, NAME, ISSUE, AGE, GENDER, FEES, MOBILE_NO, BILL_NO, USERNAME,
                BLOOD_GROUP, ALLERGIES, MEDICAL_HISTORY, GUARDIAN_NAME
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, issue, age, gender, fees, mobile, bill_no, username, blood_group, allergies, med_history, guardian_name),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({"error": "Duplicate patient identifier: " + str(e)}), 409

    conn.close()
    return jsonify({"message": f"Patient record created with ID {pid}", "PID": pid}), 201


@app.route("/api/patients/<pid>", methods=["DELETE"])
@staff_required
def delete_patient(pid):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM CONSULTATION WHERE PATIENT_ID = ?", (pid,))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return jsonify({"error": "Cannot delete patient with active consultation history."}), 400

    cursor.execute("DELETE FROM PATIENTS WHERE PID = ?", (pid,))
    cursor.execute("UPDATE BEDS SET STATUS = 'Available', PATIENT_ID = NULL, ASSIGNED_DATE = NULL WHERE PATIENT_ID = ?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Patient {pid} deleted successfully"})


# ================= EMERGENCY AMBULANCE TRANSPORT =================

@app.route("/api/emt", methods=["GET"])
@login_required
def get_emt():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT E.VNO, E.VTYPE, E.DRIVER_NAME, E.MOBILE_NO, COALESCE(S.STATUS, 'Available') AS STATUS
        FROM EMT E
        LEFT JOIN EMT_STATUS S ON E.VNO = S.VNO
        ORDER BY E.VNO ASC
    """
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/emt", methods=["POST"])
@staff_required
def add_emt():
    data = request.get_json() or {}
    vno = data.get("VNO", "").strip().upper()
    vtype = data.get("VTYPE", "").strip()
    driver = data.get("DRIVER_NAME", "").strip()
    mobile = data.get("MOBILE_NO", "").strip()
    status = data.get("STATUS", "Available")

    if not vno or not driver:
        return jsonify({"error": "Vehicle No and Driver Name are required"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO EMT (VNO, VTYPE, DRIVER_NAME, MOBILE_NO) VALUES (?, ?, ?, ?)", (vno, vtype, driver, mobile))
        cursor.execute("INSERT OR REPLACE INTO EMT_STATUS (VNO, STATUS) VALUES (?, ?)", (vno, status))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": f"Ambulance {vno} already registered"}), 409

    conn.close()
    return jsonify({"message": f"Ambulance {vno} added successfully"}), 201


@app.route("/api/emt/<vno>/status", methods=["PATCH"])
@staff_required
def update_emt_status(vno):
    data = request.get_json() or {}
    status = data.get("STATUS")
    if status not in ["Available", "Dispatched", "Maintenance"]:
        return jsonify({"error": "Invalid ambulance status"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO EMT_STATUS (VNO, STATUS) VALUES (?, ?)", (vno, status))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Ambulance {vno} status updated to {status}"})


# ================= CONSULTATIONS =================

@app.route("/api/consultations", methods=["GET"])
@login_required
def get_consultations():
    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT C.*, P.NAME AS PATIENT_NAME, P.AGE AS PATIENT_AGE, P.GENDER AS PATIENT_GENDER,
               E.NAME AS DOCTOR_NAME, E.DEPARTMENT
        FROM CONSULTATION C
        JOIN PATIENTS P ON C.PATIENT_ID = P.PID
        JOIN EMPLOYEES E ON C.EMP_ID = E.EID
    """
    params = []

    if session.get("role") == "patient":
        query += " WHERE P.USERNAME = ? OR P.MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)"
        params = [session["user"], session["user"]]

    query += " ORDER BY C.TIME DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/consultations/<cid>", methods=["GET"])
@login_required
def get_single_consultation(cid):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT C.*, P.NAME AS PATIENT_NAME, P.AGE AS PATIENT_AGE, P.GENDER AS PATIENT_GENDER,
               P.MOBILE_NO AS PATIENT_MOBILE, E.NAME AS DOCTOR_NAME, E.DEPARTMENT
        FROM CONSULTATION C
        JOIN PATIENTS P ON C.PATIENT_ID = P.PID
        JOIN EMPLOYEES E ON C.EMP_ID = E.EID
        WHERE C.CONSULTATION_ID = ?
    """,
        (cid,),
    )
    row = cursor.fetchone()
    if row and session.get("role") != "staff" and row["PATIENT_ID"] not in current_patient_ids(cursor):
        row = None
    conn.close()
    if not row:
        return jsonify({"error": "Consultation not found"}), 404
    return jsonify(dict(row))


@app.route("/api/consultations", methods=["POST"])
@login_required
def book_consultation():
    data = request.get_json() or {}
    patient_id = data.get("PATIENT_ID")
    emp_id = data.get("EMP_ID")
    reason = data.get("REASON", "General Checkup")
    # Patients are always charged the published fee shown before booking; only staff may override it.
    fees = data.get("FEES", CONSULTATION_FEE) if session.get("role") == "staff" else CONSULTATION_FEE
    time = data.get("TIME") or datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = get_db()
    cursor = conn.cursor()

    if session.get("role") == "patient":
        cursor.execute("SELECT PID FROM PATIENTS WHERE USERNAME = ? OR MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)", (session["user"], session["user"]))
        p_row = cursor.fetchone()
        if p_row:
            patient_id = p_row["PID"]
        else:
            conn.close()
            return jsonify({"error": "No patient profile associated with this account."}), 400

    if not patient_id or not emp_id:
        conn.close()
        return jsonify({"error": "Patient ID and Doctor ID are required"}), 400

    cursor.execute("SELECT COUNT(*) FROM CONSULTATION")
    next_idx = cursor.fetchone()[0] + 1
    cid = f"CON-{next_idx:03d}"

    cursor.execute(
        "INSERT INTO CONSULTATION (CONSULTATION_ID, PATIENT_ID, EMP_ID, REASON, FEES, TIME, STATUS) VALUES (?, ?, ?, ?, ?, ?, 'Scheduled')",
        (cid, patient_id, emp_id, reason, fees, time),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": f"Consultation scheduled successfully. Fee: ₹{float(fees):.2f}", "CONSULTATION_ID": cid}), 201


# ================= DIGITAL PRESCRIPTIONS =================

@app.route("/api/prescriptions", methods=["GET"])
@login_required
def get_prescriptions():
    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT PR.PRESCRIPTION_ID, PR.CONSULTATION_ID, PR.DATE, PR.DIAGNOSIS, PR.INSTRUCTIONS,
               P.NAME AS PATIENT_NAME, P.PID AS PATIENT_ID, P.AGE AS PATIENT_AGE, P.GENDER AS PATIENT_GENDER,
               P.MOBILE_NO AS PATIENT_MOBILE, E.NAME AS DOCTOR_NAME, E.DEPARTMENT
        FROM PRESCRIPTION PR
        JOIN CONSULTATION C ON PR.CONSULTATION_ID = C.CONSULTATION_ID
        JOIN PATIENTS P ON C.PATIENT_ID = P.PID
        JOIN EMPLOYEES E ON C.EMP_ID = E.EID
    """
    params = []
    if session.get("role") == "patient":
        query += " WHERE P.USERNAME = ? OR P.MOBILE_NO = (SELECT MOBILE_NO FROM USER_DATA WHERE USERNAME = ?)"
        params = [session["user"], session["user"]]

    query += " ORDER BY PR.DATE DESC"
    cursor.execute(query, params)
    prescriptions = [dict(r) for r in cursor.fetchall()]

    for pres in prescriptions:
        cursor.execute("SELECT * FROM PRESCRIBED_MEDICINE WHERE PRESCRIPTION_ID = ?", (pres["PRESCRIPTION_ID"],))
        pres["medicines"] = [dict(m) for m in cursor.fetchall()]

    conn.close()
    return jsonify(prescriptions)


@app.route("/api/prescriptions/<rx_id>", methods=["GET"])
@login_required
def get_prescription_details(rx_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT PR.PRESCRIPTION_ID, PR.CONSULTATION_ID, PR.DATE, PR.DIAGNOSIS, PR.INSTRUCTIONS,
               P.NAME AS PATIENT_NAME, P.PID AS PATIENT_ID, P.AGE AS PATIENT_AGE, P.GENDER AS PATIENT_GENDER,
               P.MOBILE_NO AS PATIENT_MOBILE, P.BILL_NO, E.NAME AS DOCTOR_NAME, E.DEPARTMENT, E.EID AS DOCTOR_ID
        FROM PRESCRIPTION PR
        JOIN CONSULTATION C ON PR.CONSULTATION_ID = C.CONSULTATION_ID
        JOIN PATIENTS P ON C.PATIENT_ID = P.PID
        JOIN EMPLOYEES E ON C.EMP_ID = E.EID
        WHERE PR.PRESCRIPTION_ID = ?
    """,
        (rx_id,),
    )
    pres = cursor.fetchone()
    if pres and session.get("role") != "staff" and pres["PATIENT_ID"] not in current_patient_ids(cursor):
        pres = None
    if not pres:
        conn.close()
        return jsonify({"error": "Prescription not found"}), 404

    pres_dict = dict(pres)
    cursor.execute("SELECT * FROM PRESCRIBED_MEDICINE WHERE PRESCRIPTION_ID = ?", (rx_id,))
    pres_dict["medicines"] = [dict(m) for m in cursor.fetchall()]

    conn.close()
    return jsonify(pres_dict)


@app.route("/api/prescriptions", methods=["POST"])
@staff_required
def create_prescription():
    data = request.get_json() or {}
    consultation_id = data.get("CONSULTATION_ID")
    diagnosis = data.get("DIAGNOSIS", "").strip()
    instructions = data.get("INSTRUCTIONS", "").strip()
    medicines = data.get("MEDICINES", [])
    date_str = datetime.now().strftime("%Y-%m-%d")

    if not consultation_id:
        return jsonify({"error": "Consultation ID is required"}), 400
    if not diagnosis:
        return jsonify({"error": "Clinical diagnosis is required"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM PRESCRIPTION")
    next_idx = cursor.fetchone()[0] + 1
    pres_id = f"RX-{next_idx:03d}"

    try:
        cursor.execute(
            "INSERT INTO PRESCRIPTION (PRESCRIPTION_ID, CONSULTATION_ID, DATE, DIAGNOSIS, INSTRUCTIONS) VALUES (?, ?, ?, ?, ?)",
            (pres_id, consultation_id, date_str, diagnosis, instructions),
        )

        for med in medicines:
            med_name = med.get("name")
            if not med_name:
                continue
            dosage = med.get("dosage", "1 Tablet")
            freq = med.get("frequency", "Twice daily")
            dur = med.get("duration", "5 Days")

            cursor.execute(
                "INSERT INTO PRESCRIBED_MEDICINE (PRESCRIPTION_ID, MEDICINE_NAME, DOSAGE, FREQUENCY, DURATION) VALUES (?, ?, ?, ?, ?)",
                (pres_id, med_name, dosage, freq, dur),
            )
            cursor.execute("UPDATE PHARMACY SET STOCK = MAX(0, STOCK - 1) WHERE MEDICINE_NAME = ?", (med_name,))

        cursor.execute("UPDATE CONSULTATION SET STATUS = 'Completed' WHERE CONSULTATION_ID = ?", (consultation_id,))
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({"error": f"Could not create prescription: {str(e)}"}), 400

    conn.close()
    return jsonify({"message": "Digital Prescription created successfully", "PRESCRIPTION_ID": pres_id}), 201


# ================= NOTIFICATIONS & DATABASE RESET =================

@app.route("/api/notifications", methods=["GET"])
@staff_required
def get_notifications():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM NOTIFICATIONS ORDER BY ID DESC LIMIT 20")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/admin/reset", methods=["POST"])
@staff_required
def reset_database():
    if not DEMO_MODE:
        return jsonify({"error": "Database reset is only available in demo mode."}), 403
    conn = get_db()
    cursor = conn.cursor()
    tables = [
        "DATA_REQUESTS",
        "NOTIFICATIONS",
        "PRESCRIBED_MEDICINE",
        "PRESCRIPTION",
        "CONSULTATION",
        "MEDICINE_PURCHASES",
        "BEDS",
        "EMT_STATUS",
        "EMT",
        "PHARMACY",
        "PATIENTS",
        "EMPLOYEES",
        "USER_DATA",
    ]
    for t in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    conn.close()
    init_db(demo_mode=DEMO_MODE)
    return jsonify({"message": "Database reset and seeded with fictional demo data."})


# ================= PRIVACY: DATA EXPORT, DELETION REQUESTS & PREFERENCES =================

@app.route("/api/privacy/export", methods=["GET"])
@login_required
def export_my_data():
    """Right of access / portability: everything the portal stores about the signed-in user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT USERNAME, ROLE, NAME, MOBILE_NO, CREATED_AT, TERMS_ACCEPTED_AT, POLICY_VERSION,
                  HEALTH_DATA_CONSENT_AT, MARKETING_OPT_IN, IS_MINOR, GUARDIAN_NAME, GUARDIAN_CONSENT_AT
           FROM USER_DATA WHERE USERNAME = ?""",
        (session["user"],),
    )
    account = cursor.fetchone()
    pids = sorted(current_patient_ids(cursor)) if session.get("role") == "patient" else []
    placeholders = ",".join("?" * len(pids))

    def rows(query, params=()):
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

    export = {
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "controller": BUSINESS["name"],
        "account": dict(account) if account else None,
        "patient_records": rows(f"SELECT * FROM PATIENTS WHERE PID IN ({placeholders})", pids) if pids else [],
        "consultations": rows(f"SELECT * FROM CONSULTATION WHERE PATIENT_ID IN ({placeholders})", pids) if pids else [],
        "prescriptions": rows(
            f"""SELECT PR.*, PM.MEDICINE_NAME, PM.DOSAGE, PM.FREQUENCY, PM.DURATION
                FROM PRESCRIPTION PR
                JOIN CONSULTATION C ON PR.CONSULTATION_ID = C.CONSULTATION_ID
                LEFT JOIN PRESCRIBED_MEDICINE PM ON PM.PRESCRIPTION_ID = PR.PRESCRIPTION_ID
                WHERE C.PATIENT_ID IN ({placeholders})""",
            pids,
        ) if pids else [],
        "bed_reservations": rows(f"SELECT BED_ID, WARD_TYPE, BED_NUMBER, ASSIGNED_DATE FROM BEDS WHERE PATIENT_ID IN ({placeholders})", pids) if pids else [],
        "medicine_purchases": rows("SELECT * FROM MEDICINE_PURCHASES WHERE USERNAME = ?", (session["user"],)),
        "privacy_requests": rows("SELECT * FROM DATA_REQUESTS WHERE USERNAME = ?", (session["user"],)),
    }
    conn.close()
    return Response(
        json.dumps(export, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=pulsecare-data-{session['user']}.json"},
    )


@app.route("/api/privacy/deletion-request", methods=["GET"])
@login_required
def get_my_deletion_requests():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM DATA_REQUESTS WHERE USERNAME = ? ORDER BY ID DESC", (session["user"],))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/privacy/deletion-request", methods=["POST"])
@login_required
def create_deletion_request():
    data = request.get_json() or {}
    password = (data.get("password") or "").strip()
    reason = (data.get("reason") or "").strip()[:500] or None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT PASSWORD FROM USER_DATA WHERE USERNAME = ?", (session["user"],))
    row = cursor.fetchone()
    if not row or not check_password_hash(row["PASSWORD"], password):
        conn.close()
        return jsonify({"error": "Please confirm your password to request deletion."}), 401

    cursor.execute("SELECT ID FROM DATA_REQUESTS WHERE USERNAME = ? AND STATUS = 'Pending'", (session["user"],))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "You already have a pending deletion request."}), 409

    cursor.execute("INSERT INTO DATA_REQUESTS (USERNAME, REQUEST_TYPE, REASON) VALUES (?, 'deletion', ?)", (session["user"], reason))
    cursor.execute("INSERT INTO NOTIFICATIONS (TYPE, MESSAGE) VALUES ('privacy', ?)", (f"Data deletion requested by @{session['user']}.",))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deletion request received. We will process it within 30 days and record the outcome in your privacy panel."}), 201


@app.route("/api/privacy/requests", methods=["GET"])
@staff_required
def list_privacy_requests():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM DATA_REQUESTS ORDER BY CASE STATUS WHEN 'Pending' THEN 0 ELSE 1 END, ID DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/privacy/requests/<int:request_id>/complete", methods=["POST"])
@staff_required
def complete_privacy_request(request_id):
    """Erase the account and non-clinical personal data.

    Clinical records (consultations and prescriptions) are retained, unlinked from the
    login, for the statutory medical-record retention period described in the Privacy Policy.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM DATA_REQUESTS WHERE ID = ?", (request_id,))
    req = cursor.fetchone()
    if not req:
        conn.close()
        return jsonify({"error": "Request not found"}), 404
    if req["STATUS"] != "Pending":
        conn.close()
        return jsonify({"error": "Request has already been resolved"}), 409

    username = req["USERNAME"]
    if username == session["user"]:
        conn.close()
        return jsonify({"error": "Another staff member must process your own deletion request."}), 403

    cursor.execute("SELECT PID FROM PATIENTS WHERE USERNAME = ?", (username,))
    pids = [r["PID"] for r in cursor.fetchall()]
    retained = []
    for pid in pids:
        cursor.execute("SELECT COUNT(*) FROM CONSULTATION WHERE PATIENT_ID = ?", (pid,))
        has_clinical_records = cursor.fetchone()[0] > 0
        cursor.execute("UPDATE BEDS SET STATUS = 'Available', PATIENT_ID = NULL, ASSIGNED_DATE = NULL WHERE PATIENT_ID = ?", (pid,))
        if has_clinical_records:
            cursor.execute("UPDATE PATIENTS SET USERNAME = NULL WHERE PID = ?", (pid,))
            retained.append(pid)
        else:
            cursor.execute("DELETE FROM PATIENTS WHERE PID = ?", (pid,))

    cursor.execute(
        "UPDATE MEDICINE_PURCHASES SET PATIENT_NAME = 'Deleted user', USERNAME = NULL WHERE USERNAME = ? OR PATIENT_ID IN ({})".format(
            ",".join("?" * len(pids)) or "NULL"
        ),
        (username, *pids),
    )
    cursor.execute("DELETE FROM USER_DATA WHERE USERNAME = ?", (username,))

    note = "Account and non-clinical personal data erased."
    if retained:
        note += f" Clinical records for {', '.join(retained)} retained under medical-record retention law and unlinked from the login."
    cursor.execute(
        "UPDATE DATA_REQUESTS SET STATUS = 'Completed', RESOLUTION_NOTE = ?, RESOLVED_AT = CURRENT_TIMESTAMP, RESOLVED_BY = ? WHERE ID = ?",
        (note, session["user"], request_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": note})


@app.route("/api/privacy/requests/<int:request_id>/reject", methods=["POST"])
@staff_required
def reject_privacy_request(request_id):
    data = request.get_json() or {}
    note = (data.get("note") or "").strip()
    if not note:
        return jsonify({"error": "A reason is required when rejecting a request."}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE DATA_REQUESTS SET STATUS = 'Rejected', RESOLUTION_NOTE = ?, RESOLVED_AT = CURRENT_TIMESTAMP, RESOLVED_BY = ? WHERE ID = ? AND STATUS = 'Pending'",
        (note[:500], session["user"], request_id),
    )
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    if not updated:
        return jsonify({"error": "Pending request not found"}), 404
    return jsonify({"message": "Request rejected and reason recorded."})


@app.route("/api/account/preferences", methods=["PUT"])
@login_required
def update_preferences():
    data = request.get_json() or {}
    opt_in = 1 if data.get("marketing_opt_in") is True else 0
    conn = get_db()
    conn.execute("UPDATE USER_DATA SET MARKETING_OPT_IN = ? WHERE USERNAME = ?", (opt_in, session["user"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "Communication preferences saved.", "marketing_opt_in": bool(opt_in)})


def _simple_page(title, body_html):
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{html.escape(title)} | PulseCare+</title>
<link rel="stylesheet" href="/legal/legal.css"></head><body><main class="legal-main" id="main">
<h1>{html.escape(title)}</h1>{body_html}<p><a href="/">Return to PulseCare+</a></p></main></body></html>"""


@app.route("/unsubscribe", methods=["GET", "POST"])
def unsubscribe():
    """Unsubscribe link used in every marketing email (supports RFC 8058 one-click POST)."""
    token = request.values.get("token", "")
    username = read_unsubscribe_token(app.config["SECRET_KEY"], token)
    if not username:
        return _simple_page("Invalid link", "<p>This unsubscribe link is invalid or has expired.</p>"), 400

    if request.method == "POST":
        conn = get_db()
        conn.execute("UPDATE USER_DATA SET MARKETING_OPT_IN = 0 WHERE USERNAME = ?", (username,))
        conn.commit()
        conn.close()
        return _simple_page("You have been unsubscribed", "<p>You will no longer receive optional updates from us. "
                            "Service messages about your appointments may still be sent.</p>")

    safe_token = html.escape(token, quote=True)
    return _simple_page(
        "Unsubscribe from updates",
        f"""<p>Confirm that you no longer want to receive optional health tips and hospital updates.</p>
<form method="post" action="/unsubscribe"><input type="hidden" name="token" value="{safe_token}">
<button type="submit">Unsubscribe</button></form>""",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
