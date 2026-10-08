from fastapi import APIRouter, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.oauth import OAuthToken, OAuthApp
from app.services.price_simulator import market_indices, is_market_open

router = APIRouter(tags=["User Profile"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tokens = db.query(OAuthToken).filter(
        OAuthToken.user_id == user.id,
        OAuthToken.is_revoked == False
    ).order_by(OAuthToken.created_at.desc()).all()

    # Join app info
    connected_apps = []
    for tok in tokens:
        app_obj = db.query(OAuthApp).filter(OAuthApp.client_id == tok.client_id).first()
        connected_apps.append({
            "token_id": tok.id,
            "app_name": app_obj.name if app_obj else tok.client_id,
            "client_id": tok.client_id,
            "token_preview": tok.token_preview,
            "scope": tok.scope,
            "created_at": tok.created_at,
            "expires_at": tok.expires_at
        })

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "connected_apps": connected_apps,
            "indices": market_indices,
            "market_open": is_market_open(db),
            "active_tab": "profile"
        }
    )

@router.post("/profile/revoke-app/{token_id}")
async def revoke_app_action(
    token_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tok = db.query(OAuthToken).filter(OAuthToken.id == token_id, OAuthToken.user_id == user.id).first()
    if tok:
        tok.is_revoked = True
        db.commit()
    return RedirectResponse(url="/profile?success=Application access revoked successfully", status_code=status.HTTP_303_SEE_OTHER)
