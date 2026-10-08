from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_optional_user
from app.models.oauth import OAuthApp
from app.services.oauth_service import validate_client, create_authorization_code, exchange_code_for_token, revoke_token

router = APIRouter(tags=["OAuth"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_page(
    request: Request,
    client_id: str,
    redirect_uri: str,
    state: Optional[str] = "",
    response_type: Optional[str] = "code",
    db: Session = Depends(get_db),
    user = Depends(get_optional_user)
):
    app = validate_client(db, client_id, redirect_uri)
    if not app:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "title": "Invalid OAuth Request",
                "error_message": "Invalid client_id or unauthorized redirect_uri.",
                "user": user,
                "broker_name": settings.BROKER_NAME
            },
            status_code=400
        )

    # If user is not logged in, show consent page with embedded login form or redirect
    return templates.TemplateResponse(
        request=request,
        name="oauth_authorize.html",
        context={
            "app": app,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "user": user,
            "broker_name": settings.BROKER_NAME
        }
    )

@router.post("/oauth/authorize")
async def oauth_authorize_action(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    state: Optional[str] = Form(""),
    action: str = Form(...), # "allow" or "deny"
    db: Session = Depends(get_db),
    user = Depends(get_optional_user)
):
    app = validate_client(db, client_id, redirect_uri)
    if not app:
        raise HTTPException(status_code=400, detail="Invalid client or redirect URI")

    if not user:
        # User submitted without being logged in
        return RedirectResponse(
            url=f"/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&state={state}",
            status_code=status.HTTP_303_SEE_OTHER
        )

    if action != "allow":
        delim = "&" if "?" in redirect_uri else "?"
        deny_url = f"{redirect_uri}{delim}error=access_denied&state={state}"
        return RedirectResponse(url=deny_url, status_code=status.HTTP_303_SEE_OTHER)

    # Generate Auth code
    code = create_authorization_code(db, client_id, user.id, redirect_uri)
    delim = "&" if "?" in redirect_uri else "?"
    success_url = f"{redirect_uri}{delim}code={code}&state={state}"
    return RedirectResponse(url=success_url, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/oauth/token")
async def oauth_token_endpoint(
    client_id: str = Form(...),
    client_secret: str = Form(...),
    code: str = Form(...),
    redirect_uri: Optional[str] = Form(None),
    grant_type: Optional[str] = Form("authorization_code"),
    db: Session = Depends(get_db)
):
    success, data, status_code = exchange_code_for_token(
        db=db,
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri
    )
    return JSONResponse(content=data, status_code=status_code)

@router.post("/oauth/revoke")
async def oauth_revoke_endpoint(
    token: str = Form(...),
    db: Session = Depends(get_db)
):
    revoked = revoke_token(db, token)
    return JSONResponse(content={"status": "success", "revoked": revoked})
