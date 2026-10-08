import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Order, Trade, Transaction
from app.models.oauth import OAuthToken
from app.models.system import SystemConfig
from app.services.seed_service import seed_database
from app.services.price_simulator import is_market_open

router = APIRouter(prefix="/admin", tags=["Admin & Demo Controls"])
templates = Jinja2Templates(directory="app/templates")

def is_admin_authenticated(request: Request) -> bool:
    return request.session.get("is_admin") is True if hasattr(request, "session") else request.cookies.get("admin_auth") == settings.ADMIN_PASSWORD

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    db: Session = Depends(get_db)
):
    if request.cookies.get("admin_auth") != settings.ADMIN_PASSWORD:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"broker_name": settings.BROKER_NAME, "error": None}
        )

    users = db.query(User).all()
    instruments = db.query(Instrument).order_by(Instrument.symbol).all()
    active_tokens = db.query(OAuthToken).filter(OAuthToken.is_revoked == False).all()
    
    # System configs
    market_open = is_market_open(db)
    
    outage_cfg = db.query(SystemConfig).filter(SystemConfig.key == "simulate_outage").first()
    is_outage = False
    outage_remaining = 0
    if outage_cfg and outage_cfg.value != "false":
        try:
            diff = float(outage_cfg.value) - time.time()
            if diff > 0:
                is_outage = True
                outage_remaining = int(diff)
        except ValueError:
            pass

    slow_cfg = db.query(SystemConfig).filter(SystemConfig.key == "slow_mode").first()
    is_slow_mode = (slow_cfg.value.lower() == "true") if slow_cfg else False

    # Holdings list for direct edit
    all_holdings = db.query(Holding).all()

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "users": users,
            "instruments": instruments,
            "tokens": active_tokens,
            "holdings": all_holdings,
            "market_open": market_open,
            "is_outage": is_outage,
            "outage_remaining": outage_remaining,
            "is_slow_mode": is_slow_mode
        }
    )

@router.post("/login")
async def admin_login_action(
    password: str = Form(...),
):
    if password == settings.ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="admin_auth", value=settings.ADMIN_PASSWORD, httponly=True)
        return response
    
    return RedirectResponse(url="/admin?error=Invalid admin password", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/simulate-trade")
async def simulate_trade_action(
    user_id: int = Form(...),
    symbol: str = Form(...),
    side: str = Form(...), # BUY, SELL
    quantity: int = Form(...),
    price: float = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if not user or not inst or quantity <= 0:
        return RedirectResponse(url="/admin?error=Invalid trade parameters", status_code=status.HTTP_303_SEE_OTHER)

    trade_val = round(quantity * price, 2)
    holding = db.query(Holding).filter(Holding.user_id == user.id, Holding.instrument_id == inst.id).first()

    if side == "BUY":
        if holding:
            new_qty = holding.quantity + quantity
            new_avg = round(((holding.quantity * holding.average_price) + trade_val) / new_qty, 2)
            holding.quantity = new_qty
            holding.average_price = new_avg
        else:
            db.add(Holding(
                user_id=user.id,
                instrument_id=inst.id,
                quantity=quantity,
                average_price=price
            ))
        user.available_funds = round(user.available_funds - trade_val, 2)
    else: # SELL
        if holding:
            holding.quantity = max(0, holding.quantity - quantity)
            if holding.quantity == 0:
                db.delete(holding)
        user.available_funds = round(user.available_funds + trade_val, 2)

    # Log order and trade
    ord_id = f"ADM-ORD-{int(time.time())}"
    ord_obj = Order(
        order_id=ord_id,
        user_id=user.id,
        instrument_id=inst.id,
        transaction_type=side,
        order_type="MARKET",
        product_type="CNC",
        quantity=quantity,
        price=price,
        average_executed_price=price,
        status="EXECUTED",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        executed_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(ord_obj)
    db.flush()

    db.add(Trade(
        trade_id=f"ADM-TRD-{int(time.time())}",
        order_id=ord_obj.id,
        user_id=user.id,
        instrument_id=inst.id,
        transaction_type=side,
        product_type="CNC",
        quantity=quantity,
        price=price,
        trade_time=datetime.now(timezone.utc).replace(tzinfo=None)
    ))
    db.commit()

    return RedirectResponse(url=f"/admin?success=Simulated {side} {quantity} {inst.symbol} @ ₹{price} for {user.username}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/expire-token")
async def expire_token_action(
    token_id: int = Form(...),
    db: Session = Depends(get_db)
):
    tok = db.query(OAuthToken).filter(OAuthToken.id == token_id).first()
    if tok:
        # Expire immediately
        tok.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()
        return RedirectResponse(url=f"/admin?success=Expired token {tok.token_preview} immediately (triggers 401 token_expired)", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/admin?error=Token not found", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/toggle-market")
async def toggle_market_action(db: Session = Depends(get_db)):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "market_open").first()
    if not cfg:
        cfg = SystemConfig(key="market_open", value="true")
        db.add(cfg)
    
    new_val = "false" if cfg.value.lower() == "true" else "true"
    cfg.value = new_val
    db.commit()
    state = "OPEN" if new_val == "true" else "CLOSED"
    return RedirectResponse(url=f"/admin?success=Market is now {state}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/toggle-outage")
async def toggle_outage_action(db: Session = Depends(get_db)):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "simulate_outage").first()
    if not cfg:
        cfg = SystemConfig(key="simulate_outage", value="false")
        db.add(cfg)

    # If currently active, turn off. Otherwise turn on for 60 seconds.
    is_active = False
    try:
        if cfg.value != "false" and float(cfg.value) > time.time():
            is_active = True
    except ValueError:
        pass

    if is_active:
        cfg.value = "false"
        msg = "Outage cleared. API is restored."
    else:
        cfg.value = str(time.time() + 60.0) # Active for next 60 seconds
        msg = "Simulated outage enabled for 60 seconds (API returns 503)."

    db.commit()
    return RedirectResponse(url=f"/admin?success={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/toggle-slow-mode")
async def toggle_slow_mode_action(db: Session = Depends(get_db)):
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "slow_mode").first()
    if not cfg:
        cfg = SystemConfig(key="slow_mode", value="false")
        db.add(cfg)

    new_val = "false" if cfg.value.lower() == "true" else "true"
    cfg.value = new_val
    db.commit()
    msg = "Slow mode ENABLED (+5s latency on API)" if new_val == "true" else "Slow mode DISABLED"
    return RedirectResponse(url=f"/admin?success={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/reset-data")
async def reset_data_action(db: Session = Depends(get_db)):
    seed_database(db, force_reset=True)
    return RedirectResponse(url="/admin?success=All database state reset to pristine seed data!", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/save-holding")
async def save_holding_action(
    user_id: int = Form(...),
    instrument_id: int = Form(...),
    quantity: int = Form(...),
    average_price: float = Form(...),
    db: Session = Depends(get_db)
):
    holding = db.query(Holding).filter(Holding.user_id == user_id, Holding.instrument_id == instrument_id).first()
    if quantity <= 0:
        if holding:
            db.delete(holding)
            db.commit()
            return RedirectResponse(url="/admin?success=Holding removed", status_code=status.HTTP_303_SEE_OTHER)
    else:
        if holding:
            holding.quantity = quantity
            holding.average_price = average_price
        else:
            db.add(Holding(user_id=user_id, instrument_id=instrument_id, quantity=quantity, average_price=average_price))
        db.commit()
    return RedirectResponse(url="/admin?success=Holding saved successfully", status_code=status.HTTP_303_SEE_OTHER)
