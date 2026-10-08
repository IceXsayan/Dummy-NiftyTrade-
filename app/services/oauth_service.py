from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password, hash_token, generate_random_token
from app.models.oauth import OAuthApp, OAuthAuthCode, OAuthToken
from app.models.user import User

def validate_client(db: Session, client_id: str, redirect_uri: Optional[str] = None) -> Optional[OAuthApp]:
    app = db.query(OAuthApp).filter(OAuthApp.client_id == client_id).first()
    if not app:
        return None
    if redirect_uri:
        allowed = [u.strip() for u in app.redirect_uris.split(",") if u.strip()]
        # Check matching redirect URI
        if redirect_uri not in allowed:
            return None
    return app

def create_authorization_code(db: Session, client_id: str, user_id: int, redirect_uri: str) -> str:
    code = f"nac_{generate_random_token(24)}"
    auth_code = OAuthAuthCode(
        code=code,
        client_id=client_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10),
        is_used=False
    )
    db.add(auth_code)
    db.commit()
    return code

def exchange_code_for_token(
    db: Session,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: Optional[str] = None
) -> Tuple[bool, dict, int]:
    # 1. Verify client credentials
    app = db.query(OAuthApp).filter(OAuthApp.client_id == client_id).first()
    if not app or not verify_password(client_secret, app.client_secret_hash):
        return False, {"error": "invalid_client", "error_description": "Invalid client credentials"}, 401

    # 2. Verify code
    auth_code = db.query(OAuthAuthCode).filter(
        OAuthAuthCode.code == code,
        OAuthAuthCode.client_id == client_id
    ).first()

    if not auth_code or auth_code.is_used:
        return False, {"error": "invalid_grant", "error_description": "Authorization code is invalid or already used"}, 400

    if datetime.now(timezone.utc).replace(tzinfo=None) > auth_code.expires_at:
        return False, {"error": "invalid_grant", "error_description": "Authorization code has expired"}, 400

    if redirect_uri and auth_code.redirect_uri != redirect_uri:
        return False, {"error": "invalid_grant", "error_description": "Redirect URI mismatch"}, 400

    # Mark code as used
    auth_code.is_used = True

    # 3. Generate Access Token
    raw_token = f"nt_{generate_random_token(32)}"
    thash = hash_token(raw_token)
    expires_in_secs = settings.TOKEN_EXPIRY_MINUTES * 60
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=settings.TOKEN_EXPIRY_MINUTES)

    user = db.query(User).filter(User.id == auth_code.user_id).first()

    oauth_token = OAuthToken(
        token_hash=thash,
        token_preview=raw_token[:8] + "...",
        client_id=client_id,
        user_id=auth_code.user_id,
        scope="read",
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(oauth_token)
    db.commit()

    return True, {
        "access_token": raw_token,
        "token_type": "Bearer",
        "expires_in": expires_in_secs,
        "user_id": user.client_id if user else str(auth_code.user_id),
        "scope": "read"
    }, 200

def verify_access_token(db: Session, raw_token: str) -> Tuple[bool, Optional[User], str]:
    """Verifies Bearer token, checks expiration and revocation."""
    if not raw_token:
        return False, None, "missing_token"

    thash = hash_token(raw_token)
    token_obj = db.query(OAuthToken).filter(OAuthToken.token_hash == thash).first()
    if not token_obj:
        return False, None, "invalid_token"

    if token_obj.is_revoked:
        return False, None, "token_revoked"

    if datetime.now(timezone.utc).replace(tzinfo=None) > token_obj.expires_at:
        return False, None, "token_expired"

    user = db.query(User).filter(User.id == token_obj.user_id).first()
    if not user:
        return False, None, "user_not_found"

    return True, user, "ok"

def revoke_token(db: Session, raw_token: str) -> bool:
    thash = hash_token(raw_token)
    token_obj = db.query(OAuthToken).filter(OAuthToken.token_hash == thash).first()
    if token_obj:
        token_obj.is_revoked = True
        db.commit()
        return True
    return False
