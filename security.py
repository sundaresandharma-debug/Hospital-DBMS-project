"""Input validation, rate limiting and one-time tokens shared by the API routes."""

import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^\+?[0-9]{10,15}$")
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class ValidationError(ValueError):
    """Raised for bad user input; the API turns it into a 400 with this message."""


def clean_text(value, field, *, required=True, max_len=200):
    text = (value or "").strip() if isinstance(value, str) or value is None else str(value).strip()
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > max_len:
        raise ValidationError(f"{field} must be {max_len} characters or fewer.")
    return text


def validate_username(value):
    username = (value or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValidationError("Username must be 3–30 characters: lowercase letters, numbers, dots or underscores.")
    return username


def validate_email(value, *, required=True):
    email = (value or "").strip().lower()
    if not email:
        if required:
            raise ValidationError("Email address is required.")
        return None
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValidationError("Enter a valid email address, like name@example.com.")
    return email


def validate_mobile(value, *, required=True):
    mobile = re.sub(r"[\s-]", "", value or "")
    if not mobile:
        if required:
            raise ValidationError("Mobile number is required.")
        return ""
    if not MOBILE_RE.match(mobile):
        raise ValidationError("Enter a valid mobile number of 10–15 digits, for example 9876543210.")
    return mobile


def validate_password(value):
    password = value or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer.")
    return password


def parse_int(value, field, *, minimum=None, maximum=None, required=True):
    if value is None or value == "":
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a whole number.")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} must be at most {maximum}.")
    return number


def parse_float(value, field, *, minimum=None, maximum=None, required=True):
    if value is None or value == "":
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number.")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError(f"{field} must be a number.")
    if minimum is not None and number < minimum:
        raise ValidationError(f"{field} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{field} must be at most {maximum}.")
    return number


def parse_appointment_time(value):
    """Accepts 'YYYY-MM-DD HH:MM' (or with a 'T') and rejects times in the past."""
    text = (value or "").strip().replace("T", " ")[:16]
    try:
        when = datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValidationError("Choose a valid appointment date and time.")
    if when < datetime.now() - timedelta(minutes=5):
        raise ValidationError("Appointment time must be in the future.")
    return when.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# One-time tokens (email verification, password reset). Only a hash is stored,
# so a leaked database cannot be used to take over accounts.
# ---------------------------------------------------------------------------

def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(cursor, username, purpose, lifetime):
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + lifetime).strftime(DATETIME_FORMAT)
    # A new link replaces any older unused link for the same purpose.
    cursor.execute(
        "UPDATE AUTH_TOKENS SET USED_AT = CURRENT_TIMESTAMP WHERE USERNAME = ? AND PURPOSE = ? AND USED_AT IS NULL",
        (username, purpose),
    )
    cursor.execute(
        "INSERT INTO AUTH_TOKENS (TOKEN_HASH, USERNAME, PURPOSE, EXPIRES_AT) VALUES (?, ?, ?, ?)",
        (hash_token(token), username, purpose, expires),
    )
    return token


def consume_token(cursor, token, purpose):
    """Returns the username for a valid, unused, unexpired token and marks it used; otherwise None."""
    if not token:
        return None
    cursor.execute(
        "SELECT USERNAME, EXPIRES_AT, USED_AT FROM AUTH_TOKENS WHERE TOKEN_HASH = ? AND PURPOSE = ?",
        (hash_token(token), purpose),
    )
    row = cursor.fetchone()
    if not row or row["USED_AT"] or row["EXPIRES_AT"] < datetime.now().strftime(DATETIME_FORMAT):
        return None
    cursor.execute("UPDATE AUTH_TOKENS SET USED_AT = CURRENT_TIMESTAMP WHERE TOKEN_HASH = ?", (hash_token(token),))
    return row["USERNAME"]


# ---------------------------------------------------------------------------
# Rate limiting: a sliding window of events per key (for example "login:<ip>").
# Stored in the app database, so on serverless hosting each instance counts on its
# own; use the hosting provider's firewall rules for a global limit as well.
# ---------------------------------------------------------------------------

def is_rate_limited(cursor, key, limit, window_seconds):
    now = time.time()
    cursor.execute("DELETE FROM RATE_EVENTS WHERE AT < ?", (now - 86400,))
    cursor.execute("SELECT COUNT(*) FROM RATE_EVENTS WHERE KEY = ? AND AT > ?", (key, now - window_seconds))
    if cursor.fetchone()[0] >= limit:
        return True
    cursor.execute("INSERT INTO RATE_EVENTS (KEY, AT) VALUES (?, ?)", (key, now))
    return False
