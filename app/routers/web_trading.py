import csv
import io
import time
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Position, Order, Trade, Transaction, Watchlist, WatchlistItem
from app.services.order_service import place_order, cancel_order, square_off_position
from app.services.portfolio_service import get_portfolio_summary
from app.services.price_simulator import market_indices, is_market_open

router = APIRouter(tags=["Trading & Portfolio"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(
    request: Request,
    active_wl_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user.id).all()
    if not watchlists:
        # Create default
        def_wl = Watchlist(user_id=user.id, name="Default")
        db.add(def_wl)
        db.commit()
        db.refresh(def_wl)
        watchlists = [def_wl]

    current_wl = None
    if active_wl_id:
        current_wl = next((w for w in watchlists if w.id == active_wl_id), None)
    if not current_wl:
        current_wl = watchlists[0]

    # Fetch items for active watchlist
    items = db.query(WatchlistItem).filter(WatchlistItem.watchlist_id == current_wl.id).all()
    instruments = [item.instrument for item in items]
    all_instruments = db.query(Instrument).all()

    return templates.TemplateResponse(
        request=request,
        name="watchlist.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "watchlists": watchlists,
            "current_wl": current_wl,
            "instruments": instruments,
            "all_instruments": all_instruments,
            "market_open": is_market_open(db),
            "indices": market_indices,
            "active_tab": "watchlist"
        }
    )

@router.post("/watchlist/create")
async def create_watchlist_action(
    name: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if name.strip():
        wl = Watchlist(user_id=user.id, name=name.strip())
        db.add(wl)
        db.commit()
        return RedirectResponse(url=f"/watchlist?active_wl_id={wl.id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/watchlist", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/watchlist/add")
async def add_to_watchlist_action(
    watchlist_id: int = Form(...),
    instrument_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id, Watchlist.user_id == user.id).first()
    if wl:
        exists = db.query(WatchlistItem).filter(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.instrument_id == instrument_id
        ).first()
        if not exists:
            db.add(WatchlistItem(watchlist_id=wl.id, instrument_id=instrument_id))
            db.commit()
    return RedirectResponse(url=f"/watchlist?active_wl_id={watchlist_id}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/watchlist/remove")
async def remove_from_watchlist_action(
    watchlist_id: int = Form(...),
    instrument_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    wl = db.query(Watchlist).filter(Watchlist.id == watchlist_id, Watchlist.user_id == user.id).first()
    if wl:
        item = db.query(WatchlistItem).filter(
            WatchlistItem.watchlist_id == wl.id,
            WatchlistItem.instrument_id == instrument_id
        ).first()
        if item:
            db.delete(item)
            db.commit()
    return RedirectResponse(url=f"/watchlist?active_wl_id={watchlist_id}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/api/ui/order-context")
def get_order_context(
    symbol: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.strip().upper()).first()
    if not inst:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "error", "message": f"Instrument '{symbol}' not found"}
        )

    holding = db.query(Holding).filter(
        Holding.user_id == user.id,
        Holding.instrument_id == inst.id
    ).first()
    holding_qty = holding.quantity if holding else 0

    position = db.query(Position).filter(
        Position.user_id == user.id,
        Position.instrument_id == inst.id,
        Position.product_type == "MIS"
    ).first()
    intraday_qty = position.quantity if position else 0

    return {
        "status": "success",
        "symbol": inst.symbol,
        "name": inst.name,
        "ltp": inst.current_price,
        "available_funds": round(user.available_funds, 2),
        "used_margin": round(user.used_margin, 2),
        "holding_qty": holding_qty,
        "intraday_qty": intraday_qty,
        "market_open": is_market_open(db)
    }

@router.post("/order/place")
async def place_order_action(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    content_type = request.headers.get("content-type", "")
    accept_header = request.headers.get("accept", "")
    is_json_request = "application/json" in content_type or "application/json" in accept_header

    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        form = await request.form()
        data = dict(form)

    symbol = str(data.get("symbol", "")).strip().upper()
    transaction_type = str(data.get("transaction_type", "BUY")).strip().upper()
    order_type = str(data.get("order_type", "MARKET")).strip().upper()
    product_type = str(data.get("product_type", "CNC")).strip().upper()

    raw_qty = data.get("quantity", 1)
    try:
        quantity = int(raw_qty)
    except (ValueError, TypeError):
        quantity = 0

    raw_price = data.get("price")
    price = None
    if raw_price is not None and str(raw_price).strip() != "":
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = None

    if quantity <= 0:
        err_msg = "Quantity must be greater than zero"
        if is_json_request:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "error", "message": err_msg}
            )
        redirect_target = data.get("next") or "/orders"
        delim = "&" if "?" in redirect_target else "?"
        return RedirectResponse(url=f"{redirect_target}{delim}error={err_msg}", status_code=status.HTTP_303_SEE_OTHER)

    if order_type == "LIMIT" and (price is None or price <= 0):
        err_msg = "Limit price must be specified and greater than zero"
        if is_json_request:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "error", "message": err_msg}
            )
        redirect_target = data.get("next") or "/orders"
        delim = "&" if "?" in redirect_target else "?"
        return RedirectResponse(url=f"{redirect_target}{delim}error={err_msg}", status_code=status.HTTP_303_SEE_OTHER)

    success, msg, order = place_order(
        db=db,
        user_id=user.id,
        symbol=symbol,
        transaction_type=transaction_type,
        order_type=order_type,
        product_type=product_type,
        quantity=quantity,
        price=price
    )

    if is_json_request:
        status_code = status.HTTP_200_OK if success else status.HTTP_400_BAD_REQUEST
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "success" if success else "error",
                "message": msg,
                "order_id": order.order_id if order else None,
                "available_funds": round(user.available_funds, 2)
            }
        )

    redirect_target = data.get("next") or "/orders"
    delim = "&" if "?" in redirect_target else "?"
    flag = "success" if success else "error"
    return RedirectResponse(
        url=f"{redirect_target}{delim}{flag}={msg}",
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    orders = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "orders": orders,
            "market_open": is_market_open(db),
            "indices": market_indices,
            "active_tab": "orders"
        }
    )

@router.post("/orders/cancel/{order_id}")
async def cancel_order_action(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    success, msg = cancel_order(db, user.id, order_id)
    flag = "success" if success else "error"
    return RedirectResponse(url=f"/orders?{flag}={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/positions", response_class=HTMLResponse)
async def positions_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    positions = db.query(Position).filter(Position.user_id == user.id).all()
    total_pos_pnl = sum(p.pnl for p in positions)
    return templates.TemplateResponse(
        request=request,
        name="positions.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "positions": positions,
            "total_pos_pnl": round(total_pos_pnl, 2),
            "market_open": is_market_open(db),
            "indices": market_indices,
            "active_tab": "positions"
        }
    )

@router.post("/positions/square-off/{pos_id}")
async def square_off_action(
    pos_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    success, msg = square_off_position(db, user.id, pos_id)
    flag = "success" if success else "error"
    return RedirectResponse(url=f"/positions?{flag}={msg}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/holdings", response_class=HTMLResponse)
async def holdings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    portfolio = get_portfolio_summary(db, user)
    return templates.TemplateResponse(
        request=request,
        name="holdings.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "portfolio": portfolio,
            "market_open": is_market_open(db),
            "indices": market_indices,
            "active_tab": "holdings"
        }
    )

@router.get("/funds", response_class=HTMLResponse)
async def funds_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transactions = db.query(Transaction).filter(
        Transaction.user_id == user.id
    ).order_by(Transaction.created_at.desc()).limit(50).all()

    return templates.TemplateResponse(
        request=request,
        name="funds.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "transactions": transactions,
            "indices": market_indices,
            "market_open": is_market_open(db),
            "active_tab": "funds"
        }
    )

@router.post("/funds/deposit")
async def deposit_funds_action(
    amount: float = Form(...),
    method: str = Form("UPI"),
    next: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target = next or "/funds"
    delim = "&" if "?" in target else "?"
    if amount <= 0:
        return RedirectResponse(url=f"{target}{delim}error=Amount must be positive", status_code=status.HTTP_303_SEE_OTHER)

    user.available_funds = round(user.available_funds + amount, 2)
    tx = Transaction(
        user_id=user.id,
        type="DEPOSIT",
        amount=amount,
        balance_after=user.available_funds,
        description=f"Simulated deposit via {method}",
        reference_id=f"DEP-{int(time.time())}"
    )
    db.add(tx)
    db.commit()
    return RedirectResponse(url=f"{target}{delim}success=Added ₹{amount:,.2f} to account successfully", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/funds/withdraw")
async def withdraw_funds_action(
    amount: float = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if amount <= 0:
        return RedirectResponse(url="/funds?error=Amount must be positive", status_code=status.HTTP_303_SEE_OTHER)
    if amount > user.available_funds:
        return RedirectResponse(url="/funds?error=Insufficient available funds", status_code=status.HTTP_303_SEE_OTHER)

    user.available_funds = round(user.available_funds - amount, 2)
    tx = Transaction(
        user_id=user.id,
        type="WITHDRAWAL",
        amount=amount,
        balance_after=user.available_funds,
        description=f"Simulated payout to bank {user.bank_account_masked}",
        reference_id=f"WTH-{int(time.time())}"
    )
    db.add(tx)
    db.commit()
    return RedirectResponse(url=f"/funds?success=Withdrawal request of ₹{amount:,.2f} processed", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/trades", response_class=HTMLResponse)
async def trades_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.trade_time.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="trades.html",
        context={
            "broker_name": settings.BROKER_NAME,
            "user": user,
            "trades": trades,
            "indices": market_indices,
            "market_open": is_market_open(db),
            "active_tab": "trades"
        }
    )

@router.get("/trades/download-csv")
async def download_trades_csv(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.trade_time.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Trade ID", "Order ID", "Symbol", "ISIN", "Side", "Product", "Quantity", "Price", "Turnover", "Trade Time"
    ])
    for t in trades:
        writer.writerow([
            t.trade_id,
            t.order.order_id if t.order else "",
            t.instrument.symbol,
            t.instrument.isin,
            t.transaction_type,
            t.product_type,
            t.quantity,
            t.price,
            round(t.quantity * t.price, 2),
            t.trade_time.strftime("%Y-%m-%d %H:%M:%S") if t.trade_time else ""
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=niftytrade_trades_{user.client_id}.csv"}
    )
