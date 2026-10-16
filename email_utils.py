"""Outgoing email helpers.

The portal does not send email today. Any email added later must be built with
``build_marketing_email`` (newsletters, health tips, announcements) or
``build_transactional_email`` (appointment confirmations, password resets) so
that every non-essential message carries a working unsubscribe link and the
RFC 2369 / RFC 8058 ``List-Unsubscribe`` headers that mail providers require.
"""

from email.message import EmailMessage

from itsdangerous import BadSignature, URLSafeSerializer

UNSUBSCRIBE_SALT = "pulsecare-unsubscribe"


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
        "You are receiving this because you opted in to updates from PulseCare+.\n"
        f"Unsubscribe at any time: {link}\n"
    )
    return msg


def build_transactional_email(*, sender, recipient, subject, body):
    """Service messages the user needs (no opt-in required), still identifying the sender."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(f"{body}\n\n--\nPulseCare+\n")
    return msg
