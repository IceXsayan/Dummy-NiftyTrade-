import random
import secrets
import urllib.parse
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, hash_password, create_session_token
from app.core.dependencies import get_optional_user
from app.models.user import User
from app.models.trading import Watchlist
from app.shared_identity import normalize_email, generate_identity
from app.services.portfolio_starter import generate_starter_portfolio

router = APIRouter(tags=["Web Auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next: Optional[str] = "/dashboard",
    error: Optional[str] = None,
    google_dialog: Optional[str] = None,
    user = Depends(get_optional_user)
):
    if user:
        return RedirectResponse(url=next or "/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    has_google_oauth = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "next": next,
            "error": error,
            "google_dialog": google_dialog,
            "has_google_oauth": has_google_oauth,
            "user": None
        }
    )

@router.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: Optional[str] = Form("/dashboard"),
    db: Session = Depends(get_db)
):
    clean_username = username.strip()
    clean_email = normalize_email(username)
    user = db.query(User).filter(
        (User.username == clean_username) | (User.client_id == clean_username.upper()) | (User.email == clean_email)
    ).first()


    if not user or not verify_password(password, user.hashed_password):
        has_google_oauth = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "broker_name": settings.BROKER_NAME,
                "next": next,
                "error": "Invalid username, email, or password.",
                "has_google_oauth": has_google_oauth,
                "user": None
            },
            status_code=400
        )

    session_token = create_session_token(user.id)
    response = RedirectResponse(url=next or "/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_id",
        value=session_token,
        httponly=True,
        max_age=7 * 86400,
        samesite="lax"
    )
    return response

# --- Google OAuth & Direct Google Login Flow ---

@router.get("/auth/google")
async def google_auth_start():
    """Initiates Google OAuth or redirects to direct Google sign-in modal if credentials aren't set."""
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "prompt": "select_account"
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
        return RedirectResponse(url=auth_url, status_code=status.HTTP_303_SEE_OTHER)
    else:
        # Seamless fallback: prompt for Google account email
        return RedirectResponse(url="/login?google_dialog=1", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/auth/google/callback")
async def google_auth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if error or not code:
        return RedirectResponse(url=f"/login?error=Google authentication cancelled or failed: {error or 'No code'}", status_code=status.HTTP_303_SEE_OTHER)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code"
                }
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return RedirectResponse(url="/login?error=Failed to retrieve access token from Google", status_code=status.HTTP_303_SEE_OTHER)

            user_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_info = user_resp.json()

        email = normalize_email(user_info.get("email", ""))
        google_id = str(user_info.get("id", ""))
        full_name = str(user_info.get("name", "")).strip() or email.split("@")[0].capitalize()
        picture = user_info.get("picture")

        if not email:
            return RedirectResponse(url="/login?error=No email returned by Google", status_code=status.HTTP_303_SEE_OTHER)

        return _login_or_create_google_user(db, email, full_name, google_id, picture)

    except Exception as e:
        return RedirectResponse(url=f"/login?error=Google authentication error: {str(e)}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/auth/google/direct")
async def google_direct_login(
    email: str = Form(...),
    full_name: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Direct Google account sign-in for seamless sandbox access."""
    clean_email = normalize_email(email)
    if not clean_email or "@" not in clean_email:
        return RedirectResponse(url="/login?error=Please enter a valid Google email address", status_code=status.HTTP_303_SEE_OTHER)

    name = full_name.strip() if full_name and full_name.strip() else None
    return _login_or_create_google_user(db, clean_email, name, google_id=f"g_{clean_email}")

def _login_or_create_google_user(db: Session, email: str, full_name: Optional[str], google_id: str, avatar_url: Optional[str] = None):
    clean_email = normalize_email(email)
    # Link to an already-provisioned user instead of creating duplicate account
    user = db.query(User).filter((User.email == clean_email) | (User.google_id == google_id)).first()

    if not user:
        identity = generate_identity(clean_email, full_name)
        base_username = clean_email.split("@")[0].replace(".", "_")
        username = base_username
        count = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{base_username}_{count}"
            count += 1

        client_id = identity["client_id"]
        while db.query(User).filter(User.client_id == client_id).first():
            client_id = f"NT{secrets.randbelow(90000) + 10000}"

        user = User(
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
            google_id=google_id,
            avatar_url=avatar_url,
            is_admin=False
        )
        db.add(user)
        db.flush()

        # Generate deterministic starter portfolio using instruments_shared.json
        generate_starter_portfolio(db, user)

        # Create fresh default watchlist
        wl = Watchlist(user_id=user.id, name="My Watchlist")
        db.add(wl)
        db.commit()
        db.refresh(user)

    else:
        # Link to already-provisioned user instead of creating duplicate account
        if not user.google_id:
            user.google_id = google_id
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
        if full_name and (not user.full_name or user.full_name == clean_email.split("@")[0].capitalize()):
            user.full_name = full_name
        db.commit()

    session_token = create_session_token(user.id)
    response = RedirectResponse(
        url=f"/dashboard?success=Welcome, {user.full_name}! Account loaded successfully.",
        status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        key="session_id",
        value=session_token,
        httponly=True,
        max_age=7 * 86400,
        samesite="lax"
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    error: Optional[str] = None,
    user = Depends(get_optional_user)
):
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "error": error,
            "user": None
        }
    )

@router.post("/register")
async def register_action(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    mobile: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_email = normalize_email(email)
    clean_username = username.strip()
    existing = db.query(User).filter((User.username == clean_username) | (User.email == clean_email)).first()
    if existing:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "broker_name": settings.BROKER_NAME,
                "error": "Username or Email already registered",
                "user": None
            },
            status_code=400
        )

    identity = generate_identity(clean_email, full_name)
    client_id = identity["client_id"]
    while db.query(User).filter(User.client_id == client_id).first():
        client_id = f"NT{secrets.randbelow(90000) + 10000}"

    new_user = User(
        username=clean_username,
        email=clean_email,
        full_name=full_name.strip() if full_name.strip() else identity["full_name"],
        hashed_password=hash_password(password),
        client_id=client_id,
        masked_pan=identity["masked_pan"],
        masked_demat=identity["masked_demat"],
        mobile=mobile.strip() if mobile.strip() else identity["mobile"],
        bank_name=identity["bank_name"],
        bank_account_masked=identity["bank_account_masked"],
        bank_ifsc=identity["bank_ifsc"],
        available_funds=1000000.0,
        used_margin=0.0
    )
    db.add(new_user)
    db.flush()

    # Generate deterministic starter portfolio using instruments_shared.json
    generate_starter_portfolio(db, new_user)

    # Add default watchlist
    wl = Watchlist(user_id=new_user.id, name="My Watchlist")
    db.add(wl)
    db.commit()
    db.refresh(new_user)

    # Log in
    session_token = create_session_token(new_user.id)
    response = RedirectResponse(url=f"/dashboard?success=Account created! Welcome, {new_user.full_name}! Starter portfolio and ₹10,00,000 cash balance loaded.", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session_id",
        value=session_token,
        httponly=True,
        max_age=7 * 86400,

        samesite="lax"
    )
    return response

@router.get("/logout")
async def logout_action():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_id")
    return response
