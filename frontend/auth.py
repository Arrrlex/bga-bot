"""Shared JWT cookie authentication for *.arrrlex.com apps."""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

AUTH_SECRET = os.environ.get("AUTH_SECRET", "dev-secret-change-in-production")
AUTH_EMAIL = os.environ.get("AUTH_EMAIL", "")
AUTH_PASSWORD_HASH = os.environ.get("AUTH_PASSWORD_HASH", "").encode()
AUTH_COOKIE_DOMAIN = os.environ.get("AUTH_COOKIE_DOMAIN")  # e.g. ".arrrlex.com"

COOKIE_NAME = "arrrlex_token"
TOKEN_EXPIRY_DAYS = 30


def create_token(email: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS)
    return jwt.encode({"email": email, "exp": exp}, AUTH_SECRET, algorithm="HS256")


def verify_token(token: str) -> str | None:
    """Return email if valid, None otherwise."""
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
        return payload.get("email")
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        return None


def check_credentials(email: str, password: str) -> bool:
    return (
        email == AUTH_EMAIL
        and bool(AUTH_PASSWORD_HASH)
        and bcrypt.checkpw(password.encode(), AUTH_PASSWORD_HASH)
    )


def set_auth_cookie(response, email: str):
    token = create_token(email)
    is_prod = AUTH_COOKIE_DOMAIN is not None
    kwargs = {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "secure": is_prod,
        "max_age": TOKEN_EXPIRY_DAYS * 24 * 60 * 60,
        "path": "/",
    }
    if AUTH_COOKIE_DOMAIN:
        kwargs["domain"] = AUTH_COOKIE_DOMAIN
    response.set_cookie(**kwargs)
    return response


def clear_auth_cookie(response):
    kwargs = {"key": COOKIE_NAME, "path": "/"}
    if AUTH_COOKIE_DOMAIN:
        kwargs["domain"] = AUTH_COOKIE_DOMAIN
    response.delete_cookie(**kwargs)
    return response
