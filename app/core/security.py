import hashlib
import hmac
import secrets
import time
from typing import Optional
import bcrypt

from app.core.config import settings

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def hash_token(token: str) -> str:
    """Store tokens securely as SHA-256 hashes."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def generate_random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

def create_session_token(user_id: int) -> str:
    """Creates a tamper-evident session token with timestamp."""
    timestamp = str(int(time.time()))
    payload = f"{user_id}:{timestamp}"
    signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def verify_session_token(session_str: Optional[str]) -> Optional[int]:
    if not session_str:
        return None
    parts = session_str.split(":")
    if len(parts) != 3:
        return None
    user_id_str, timestamp_str, sig = parts
    payload = f"{user_id_str}:{timestamp_str}"
    expected_sig = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    # Check max session expiry (e.g., 7 days)
    try:
        ts = int(timestamp_str)
        if time.time() - ts > 7 * 86400:
            return None
        return int(user_id_str)
    except ValueError:
        return None
