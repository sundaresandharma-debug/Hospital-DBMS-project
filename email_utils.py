"""Outgoing email helpers.

The portal sends account emails (email confirmation and password reset) with
``build_transactional_email``. Any email added later must use it, or
``build_marketing_email`` for newsletters, health tips and announcements, so that
every non-essential message carries a working unsubscribe link and the
RFC 2369 / RFC 8058 ``List-Unsubscribe`` headers that mail providers require.
"""

import os
import smtplib
from email.message import EmailMessage

from itsdangerous import BadSignature, URLSafeSerializer

UNSUBSCRIBE_SALT = "asclepio-unsubscribe"


def _serializer(secret_key):
    return URLSafeSerializer(secret_key, salt=UNSUBSCRIBE_SALT)


def make_unsubscribe_token(secret_key, username):
    return _serializer(secret_key).dumps(username)


def read_unsubscribe_token(secret_key, token):
    """Return the username the token was issued for, or None if it is invalid."""
    try:
        return _serializer(secret_key).loads(token)
    except BadSignature:
        return None


def unsubscribe_url(base_url, secret_key, username):
    return f"{base_url.rstrip('/')}/unsubscribe?token={make_unsubscribe_token(secret_key, username)}"


def build_marketing_email(*, sender, recipient, subject, body, username, base_url, secret_key):
    """Build an opt-in message. Callers must only send it when USER_DATA.MARKETING_OPT_IN = 1."""
    link = unsubscribe_url(base_url, secret_key, username)
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<{link}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(
        f"{body}\n\n"
        "--\n"
        "You are receiving this because you opted in to updates from Asclepio.\n"
        f"Unsubscribe at any time: {link}\n"
    )
    return msg


def build_transactional_email(*, sender, recipient, subject, body):
    """Service messages the user needs (no opt-in required), still identifying the sender."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(f"{body}\n\n--\nAsclepio\n")
    return msg


# ---------------------------------------------------------------------------
# Sending. Configure an SMTP provider with these environment variables:
#   SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, MAIL_FROM
# Without SMTP_HOST, messages are written to the server log instead of being sent,
# so the app still works in development (and on a demo without email set up).
# ---------------------------------------------------------------------------

def mail_sender():
    return os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or "no-reply@example.com"


def email_configured():
    return bool(os.environ.get("SMTP_HOST"))


def send_email(msg):
    """Send a message; returns True if it was handed to the SMTP server."""
    if not email_configured():
        print(f"[email not configured] To: {msg['To']} | Subject: {msg['Subject']}\n{msg.get_content()}", flush=True)
        return False
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        with server:
            if user:
                server.login(user, password or "")
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[email send failed] To: {msg['To']} | {exc}", flush=True)
        return False


def send_verification_email(recipient, name, link):
    return send_email(build_transactional_email(
        sender=mail_sender(),
        recipient=recipient,
        subject="Confirm your email for Asclepio",
        body=(
            f"Hi {name},\n\n"
            "Please confirm your email address by opening this link:\n"
            f"{link}\n\n"
            "The link works once and expires in 24 hours. If you didn't create an Asclepio account, you can ignore this email."
        ),
    ))


def send_password_reset_email(recipient, name, link):
    return send_email(build_transactional_email(
        sender=mail_sender(),
        recipient=recipient,
        subject="Reset your Asclepio password",
        body=(
            f"Hi {name},\n\n"
            "Someone asked to reset the password for your Asclepio account. To choose a new password, open this link:\n"
            f"{link}\n\n"
            "The link works once and expires in 1 hour. If you didn't ask for this, you can ignore this email; your password stays the same."
        ),
    ))
