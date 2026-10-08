from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.instrument import Instrument
from app.services.portfolio_service import get_portfolio_summary
from app.services.price_simulator import market_indices, is_market_open

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def root():
    return RedirectResponse(url="/dashboard")

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    portfolio = get_portfolio_summary(db, user)
    instruments = db.query(Instrument).all()

    # Calculate Top Gainers and Losers
    sorted_by_change = sorted(instruments, key=lambda x: x.day_change_percentage, reverse=True)
    top_gainers = sorted_by_change[:5]
    top_losers = sorted_by_change[-5:][::-1]

    market_open = is_market_open(db)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "portfolio": portfolio,
            "indices": market_indices,
            "market_open": market_open,
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "active_tab": "dashboard"
        }
    )

@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    portfolio = get_portfolio_summary(db, user)

    return templates.TemplateResponse(
        request=request,
        name="analytics.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "portfolio": portfolio,
            "indices": market_indices,
            "market_open": is_market_open(db),
            "active_tab": "analytics"
        }
    )
