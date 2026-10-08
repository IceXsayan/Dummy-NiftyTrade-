from typing import Optional
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Watchlist
from app.services.price_simulator import market_indices, is_market_open

router = APIRouter(tags=["Market & Stocks"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/market", response_class=HTMLResponse)
async def market_page(
    request: Request,
    q: Optional[str] = Query(None, description="Search symbol or name"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    asset_class: Optional[str] = Query(None, description="Filter by asset class"),
    sort: Optional[str] = Query("volume", description="Sort field: price, change, volume, name"),
    order: Optional[str] = Query("desc", description="Sort order: asc, desc"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Instrument)

    if q:
        search_pattern = f"%{q.strip().lower()}%"
        query = query.filter(
            (Instrument.symbol.ilike(search_pattern)) | 
            (Instrument.name.ilike(search_pattern)) | 
            (Instrument.isin.ilike(search_pattern))
        )

    if sector and sector != "All":
        query = query.filter(Instrument.sector == sector)

    if asset_class and asset_class != "All":
        query = query.filter(Instrument.asset_class == asset_class.lower())

    instruments = query.all()

    # Dynamic sorting
    if sort == "price":
        instruments = sorted(instruments, key=lambda x: x.current_price, reverse=(order == "desc"))
    elif sort == "change":
        instruments = sorted(instruments, key=lambda x: x.day_change_percentage, reverse=(order == "desc"))
    elif sort == "volume":
        instruments = sorted(instruments, key=lambda x: x.volume, reverse=(order == "desc"))
    elif sort == "name":
        instruments = sorted(instruments, key=lambda x: x.name, reverse=(order == "desc"))

    # Extract distinct sectors and asset classes for filter dropdowns
    all_insts = db.query(Instrument).all()
    sectors = sorted(list(set(i.sector for i in all_insts if i.sector)))
    asset_classes = sorted(list(set(i.asset_class for i in all_insts if i.asset_class)))

    # Fetch user's watchlists for quick "Add to Watchlist" dropdown
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()

    return templates.TemplateResponse(
        request=request,
        name="market.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "instruments": instruments,
            "sectors": sectors,
            "asset_classes": asset_classes,
            "selected_sector": sector,
            "selected_asset_class": asset_class,
            "selected_sort": sort,
            "selected_order": order,
            "search_query": q or "",
            "watchlists": watchlists,
            "market_open": is_market_open(db),
            "indices": market_indices,
            "active_tab": "market"
        }
    )

@router.get("/stock/{symbol}", response_class=HTMLResponse)
async def stock_detail_page(
    request: Request,
    symbol: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Stock not found")

    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()
    market_open = is_market_open(db)

    return templates.TemplateResponse(
        request=request,
        name="stock_detail.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "inst": inst,
            "watchlists": watchlists,
            "market_open": market_open,
            "indices": market_indices,
            "active_tab": "market"
        }
    )
