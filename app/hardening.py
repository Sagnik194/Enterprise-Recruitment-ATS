"""Security helpers for ATS. No database or framework dependencies."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

SESSION_MAX_AGE_SECONDS = 3600


def password_fingerprint(password_hash: str, secret: str) -> str:
    """Bind issued credentials to the current password hash without revealing it."""
    return hmac.new(secret.encode(), password_hash.encode(), hashlib.sha256).hexdigest()


def new_browser_session(session: dict, user_id: int, password_hash: str, secret: str, now: int | None = None) -> None:
    session.clear()  # rotates away anonymous CSRF/session data
    session["user_id"] = user_id
    session["authenticated_at"] = int(time.time() if now is None else now)
    session["password_version"] = password_fingerprint(password_hash, secret)
    session["csrf"] = secrets.token_urlsafe(32)


def validate_browser_session(session: dict, password_hash: str, secret: str, now: int | None = None, max_age: int = SESSION_MAX_AGE_SECONDS) -> bool:
    timestamp = session.get("authenticated_at")
    if type(timestamp) is not int or timestamp > int(time.time() if now is None else now):
        return False
    if int(time.time() if now is None else now) - timestamp >= max_age:
        return False
    expected = password_fingerprint(password_hash, secret)
    return hmac.compare_digest(str(session.get("password_version", "")), expected)


def validate_jwt_password_version(claims: dict, password_hash: str, secret: str) -> bool:
    version = claims.get("pwdv")
    return isinstance(version, str) and hmac.compare_digest(version, password_fingerprint(password_hash, secret))


def utc_timestamp() -> datetime:
    return datetime.now(timezone.utc)
