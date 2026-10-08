import asyncio
import time
from typing import Optional, Dict, List
from fastapi import Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_session_token
from app.models.user import User
from app.models.system import SystemConfig
from app.services.oauth_service import verify_access_token

# In-memory rate limiter: dict of token_hash -> list of timestamps
_rate_limit_records: Dict[str, List[float]] = {}
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60.0

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency for authenticated web routes. Redirects to login if unauthenticated, or returns 401 for /api/ and JSON endpoints."""
    cookie = request.cookies.get("session_id")
    user_id = verify_session_token(cookie)
    is_json = request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "") or "application/json" in request.headers.get("content-type", "")

    if not user_id:
        if is_json:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"status": "error", "message": "Not authenticated. Please log in."}
            )
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": f"/login?next={request.url.path}"}
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        if is_json:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"status": "error", "message": "User session expired or invalid."}
            )
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    return user

def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Dependency that returns User if logged in, else None."""
    cookie = request.cookies.get("session_id")
    user_id = verify_session_token(cookie)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()

async def get_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Dependency for Public API v1.
    1. Checks simulated outage.
    2. Checks slow mode.
    3. Enforces rate limits (60 req/min).
    4. Validates Bearer access token.
    """
    # 1. Simulated Outage Check
    outage_cfg = db.query(SystemConfig).filter(SystemConfig.key == "simulate_outage").first()
    if outage_cfg and outage_cfg.value != "false":
        try:
            until_ts = float(outage_cfg.value)
            if time.time() < until_ts:
                raise HTTPException(
                    status_code=503,
                    detail={"status": "error", "error": "service_unavailable", "message": "Broker API is temporarily unavailable (Simulated Outage)"}
                )
        except ValueError:
            if outage_cfg.value == "true":
                raise HTTPException(
                    status_code=503,
                    detail={"status": "error", "error": "service_unavailable", "message": "Broker API is temporarily unavailable (Simulated Outage)"}
                )

    # 2. Slow Mode Check
    slow_cfg = db.query(SystemConfig).filter(SystemConfig.key == "slow_mode").first()
    if slow_cfg and slow_cfg.value.lower() == "true":
        await asyncio.sleep(5)

    # 3. Extract Bearer Token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"status": "error", "error": "unauthorized", "message": "Missing or invalid Authorization header. Expected Bearer token."}
        )
    raw_token = auth_header.split(" ", 1)[1].strip()

    # 4. Rate Limiter (60 req / min)
    now = time.time()
    req_history = _rate_limit_records.get(raw_token, [])
    # Filter out requests older than window
    req_history = [t for t in req_history if now - t < RATE_LIMIT_WINDOW]
    if len(req_history) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail={"status": "error", "error": "rate_limit_exceeded", "message": "Rate limit exceeded: 60 requests per minute"}
        )
    req_history.append(now)
    _rate_limit_records[raw_token] = req_history

    # 5. Verify Token
    valid, user, err = verify_access_token(db, raw_token)
    if not valid:
        if err == "token_expired":
            raise HTTPException(
                status_code=401,
                detail={"error": "token_expired", "message": "The access token has expired. Please re-authenticate."}
            )
        elif err == "token_revoked":
            raise HTTPException(
                status_code=401,
                detail={"error": "token_revoked", "message": "The access token has been revoked."}
            )
        else:
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_token", "message": "The access token is invalid."}
            )

    return user
