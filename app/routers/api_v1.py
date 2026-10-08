from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_api_user
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Position, Order, Trade
from app.serializers import get_serializer

router = APIRouter(prefix="/api/v1", tags=["Public Data API v1"])

@router.get("/profile", summary="Get User Profile")
async def get_profile(
    user: User = Depends(get_api_user)
):
    s = get_serializer()
    return s.success(s.serialize_profile(user))

@router.get("/holdings", summary="Get Delivery Holdings")
async def get_holdings(
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    holdings = db.query(Holding).filter(Holding.user_id == user.id, Holding.quantity > 0).all()
    serialized = [s.serialize_holding(h) for h in holdings]
    return s.success(serialized)

@router.get("/positions", summary="Get Intraday Positions")
async def get_positions(
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    positions = db.query(Position).filter(Position.user_id == user.id).all()
    serialized = [s.serialize_position(p) for p in positions]
    return s.success(serialized)

@router.get("/orders", summary="Get Order Book")
async def get_orders(
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    orders = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).all()
    serialized = [s.serialize_order(o) for o in orders]
    return s.success(serialized)

@router.get("/trades", summary="Get Executed Trades")
async def get_trades(
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.trade_time.desc()).all()
    serialized = [s.serialize_trade(t) for t in trades]
    return s.success(serialized)

@router.get("/funds", summary="Get Account Funds & Margin")
async def get_funds(
    user: User = Depends(get_api_user)
):
    s = get_serializer()
    return s.success(s.serialize_funds(user))

@router.get("/quote", summary="Get Quote by ISIN or Symbol")
async def get_single_quote(
    isin: Optional[str] = Query(None, description="Stock ISIN"),
    symbol: Optional[str] = Query(None, description="Stock Symbol"),
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    query = db.query(Instrument)
    if isin:
        inst = query.filter(Instrument.isin == isin.strip().upper()).first()
    elif symbol:
        inst = query.filter(Instrument.symbol == symbol.strip().upper()).first()
    else:
        raise HTTPException(status_code=400, detail=s.error("Provide 'isin' or 'symbol' parameter"))

    if not inst:
        raise HTTPException(status_code=404, detail=s.error("Instrument not found"))

    return s.success(s.serialize_quote(inst))

@router.get("/quotes", summary="Get Quotes for Multiple ISINs")
async def get_multiple_quotes(
    isins: str = Query(..., description="Comma-separated ISINs"),
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    isin_list = [i.strip().upper() for i in isins.split(",") if i.strip()]
    instruments = db.query(Instrument).filter(Instrument.isin.in_(isin_list)).all()
    
    quote_map = {inst.isin: s.serialize_quote(inst) for inst in instruments}
    return s.success(quote_map)

@router.get("/instruments", summary="Get Instrument Master")
async def get_instruments(
    user: User = Depends(get_api_user),
    db: Session = Depends(get_db)
):
    s = get_serializer()
    instruments = db.query(Instrument).all()
    return s.success([s.serialize_instrument(inst) for inst in instruments])
