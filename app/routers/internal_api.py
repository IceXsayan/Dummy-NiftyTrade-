import secrets
import time
from collections import defaultdict
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.models.trading import Holding, Watchlist
from app.serializers import get_serializer
from app.services.portfolio_service import get_portfolio_summary
from app.services.portfolio_starter import generate_starter_portfolio
from app.shared_identity import normalize_email, generate_identity

router = APIRouter(prefix="/internal/v1", tags=["TradeOne Internal API v1"])

# In-memory sliding-window rate limiter (60 requests per minute)
_request_history = defaultdict(list)

def reset_rate_limiter():
    """Helper to reset rate limiter history (useful for testing)."""
    _request_history.clear()

def verify_internal_auth(
    request: Request,
    x_internal_key: Optional[str] = Header(None, alias="x-internal-key")
):
    """
    Authenticate internal API requests:
    1. Only active when INTERNAL_API_ENABLED=true
    2. Require x-internal-key with constant-time comparison (missing/wrong = 401)
    3. Rate limit 60/minute (HTTP 429)
    4. Never log the key.
    """
    # 1. Feature check
    enabled = settings.INTERNAL_API_ENABLED
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes")
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Internal API is disabled"
        )

    # 2. Key check with constant-time comparison
    expected_key = getattr(settings, "INTERNAL_API_KEY", "")
    if not x_internal_key or not expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal authentication key"
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(x_internal_key.encode("utf-8"), expected_key.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal authentication key"
        )

    # 3. Rate limiting (60 per 60 seconds)
    client_ip = request.client.host if request.client else "global"
    now = time.time()
    valid_window = now - 60.0
    recent_requests = [ts for ts in _request_history[client_ip] if ts > valid_window]
    _request_history[client_ip] = recent_requests

    if len(recent_requests) >= 60:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: maximum 60 requests per minute allowed"
        )

    _request_history[client_ip].append(now)

class ProvisionUserRequest(BaseModel):
    email: str
    name: Optional[str] = None
    full_name: Optional[str] = None

@router.post("/users/provision", summary="Provision User for TradeOne")
async def provision_user(
    payload: ProvisionUserRequest,
    db: Session = Depends(get_db),
    _auth = Depends(verify_internal_auth)
):
    """
    Provision a user idempotently. If user already exists, returns existing profile.
    If new user, generates deterministic fake identity, starter portfolio, and ₹10,00,000 starting wallet.
    """
    s = get_serializer()
    clean_email = normalize_email(payload.email)
    if not clean_email or "@" not in clean_email:
        raise HTTPException(status_code=400, detail=s.error("Invalid email address"))

    user = db.query(User).filter(User.email == clean_email).first()
    if user:
        # Idempotent return of existing user
        return s.success(s.serialize_profile(user), message="User already provisioned")

    # Generate deterministic identity
    requested_name = payload.full_name or payload.name
    identity = generate_identity(clean_email, requested_name)

    # Ensure unique username
    base_username = clean_email.split("@")[0].replace(".", "_")
    username = base_username
    count = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}_{count}"
        count += 1

    # Ensure unique client_id
    client_id = identity["client_id"]
    while db.query(User).filter(User.client_id == client_id).first():
        client_id = f"NT{secrets.randbelow(90000) + 10000}"

    new_user = User(
        username=username,
        email=clean_email,
        full_name=identity["full_name"],
        hashed_password=hash_password(secrets.token_urlsafe(16)),
        client_id=client_id,
        masked_pan=identity["masked_pan"],
        masked_demat=identity["masked_demat"],
        mobile=identity["mobile"],
        bank_name=identity["bank_name"],
        bank_account_masked=identity["bank_account_masked"],
        bank_ifsc=identity["bank_ifsc"],
        available_funds=1000000.0,
        used_margin=0.0,
        is_admin=False
    )
    db.add(new_user)
    db.flush()

    # Generate starter portfolio using instruments_shared.json
    generate_starter_portfolio(db, new_user)

    # Create default watchlist
    wl = Watchlist(user_id=new_user.id, name="My Watchlist")
    db.add(wl)

    db.commit()
    db.refresh(new_user)

    return s.success(s.serialize_profile(new_user), message="User provisioned successfully")

@router.get("/users/{email}/profile", summary="Get User Profile")
async def get_user_profile(
    email: str,
    db: Session = Depends(get_db),
    _auth = Depends(verify_internal_auth)
):
    s = get_serializer()
    clean_email = normalize_email(email)
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        raise HTTPException(status_code=404, detail=s.error(f"User not found for email: {clean_email}"))

    return s.success(s.serialize_profile(user))

@router.get("/users/{email}/holdings", summary="Get User Delivery Holdings")
async def get_user_holdings(
    email: str,
    db: Session = Depends(get_db),
    _auth = Depends(verify_internal_auth)
):
    """
    Returns exactly the same JSON structure, field names, number formats and pagination
    as the existing public holdings endpoint (/api/v1/holdings).
    """
    s = get_serializer()
    clean_email = normalize_email(email)
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        raise HTTPException(status_code=404, detail=s.error(f"User not found for email: {clean_email}"))

    holdings = db.query(Holding).filter(Holding.user_id == user.id, Holding.quantity > 0).all()
    serialized = [s.serialize_holding(h) for h in holdings]
    return s.success(serialized)

@router.get("/users/{email}/summary", summary="Get User Portfolio Summary")
async def get_user_summary(
    email: str,
    db: Session = Depends(get_db),
    _auth = Depends(verify_internal_auth)
):
    s = get_serializer()
    clean_email = normalize_email(email)
    user = db.query(User).filter(User.email == clean_email).first()
    if not user:
        raise HTTPException(status_code=404, detail=s.error(f"User not found for email: {clean_email}"))

    summary = get_portfolio_summary(db, user)
    return s.success({
        "user_id": user.client_id,
        "email": user.email,
        "full_name": user.full_name,
        "available_funds": summary["available_funds"],
        "used_margin": summary["used_margin"],
        "net_worth": summary["net_worth"],
        "total_invested": summary["total_invested"],
        "total_current": summary["total_current"],
        "total_pnl": summary["total_pnl"],
        "total_pnl_percentage": summary["total_pnl_percentage"],
        "day_pnl": summary["day_pnl"],
        "holdings_count": len(summary["holdings"]),
        "provider": getattr(settings, "PROVIDER_CODE", "a"),
        "broker_name": getattr(settings, "BROKER_NAME", "NiftyTrade")
    })
