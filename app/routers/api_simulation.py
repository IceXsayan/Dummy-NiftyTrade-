import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.instrument import Instrument
from app.models.system import HistoricalPrice
from app.services.price_simulator import register_subscriber, unregister_subscriber, market_indices, is_market_open

router = APIRouter(prefix="/api", tags=["Simulation & Market Feeds"])

@router.get("/live-quotes", summary="Server-Sent Events (SSE) stream for live price updates")
async def live_quotes_sse(request: Request):
    """Streams live market prices and indices every 5 seconds via SSE."""
    queue = register_subscriber()

    async def event_generator():
        try:
            # Send initial message immediately
            initial_data = {
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "indices": market_indices,
                "ticks": []
            }
            yield f"data: {json.dumps(initial_data)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=10.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unregister_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/quotes-poll", summary="Polling fallback for live price updates")
async def quotes_poll(db: Session = Depends(get_db)):
    instruments = db.query(Instrument).all()
    market_open = is_market_open(db)
    ticks = []
    for inst in instruments:
        ticks.append({
            "symbol": inst.symbol,
            "isin": inst.isin,
            "price": inst.current_price,
            "change": inst.day_change,
            "change_pct": inst.day_change_percentage,
            "high": inst.high_price,
            "low": inst.low_price,
            "volume": inst.volume
        })
    return {
        "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "market_open": market_open,
        "indices": {
            k: {
                "current": v["current"],
                "change": round(v["current"] - v["prev_close"], 2),
                "change_pct": round(((v["current"] - v["prev_close"]) / v["prev_close"]) * 100, 2),
                "high": v["high"],
                "low": v["low"]
            } for k, v in market_indices.items()
        },
        "ticks": ticks
    }

@router.get("/chart-data/{symbol}", summary="Historical chart data for 1D, 1W, 1M, 1Y")
@router.get("/simulation/chart/{symbol}", summary="Historical chart candles alias")
async def get_chart_data(
    symbol: str,
    range: str = Query("1M", pattern="^(1D|1W|1M|1Y)$"),
    db: Session = Depends(get_db)
):
    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Instrument not found")

    if range == "1D":
        # Generate simulated intraday 5-min intervals based on open, high, low, current
        points = []
        base_time = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=9, minute=15, second=0, microsecond=0)
        curr = inst.open_price
        for i in range(75): # 9:15 to 15:30 (approx 75 5-min intervals)
            t_str = (base_time + timedelta(minutes=i * 5)).strftime("%H:%M")
            # Step towards current price
            step = (inst.current_price - curr) / max(75 - i, 1)
            curr = round(max(inst.low_price * 0.999, min(inst.high_price * 1.001, curr + step)), 2)
            points.append({"time": t_str, "price": curr, "close": curr})
        candles = [{"time": p["time"], "close": p["price"]} for p in points]
        return {"symbol": inst.symbol, "range": "1D", "data": points, "candles": candles}

    # For 1W, 1M, 1Y: fetch from HistoricalPrice table
    limit_days = 7 if range == "1W" else (30 if range == "1M" else 365)
    records = db.query(HistoricalPrice).filter(
        HistoricalPrice.instrument_id == inst.id
    ).order_by(HistoricalPrice.date.desc()).limit(limit_days).all()

    # Reverse to chronological order
    records.reverse()
    points = [{"date": r.date, "time": r.date, "price": r.close, "close": r.close, "open": r.open, "high": r.high, "low": r.low, "volume": r.volume} for r in records]
    
    # Append today's latest price
    today_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
    if not points or points[-1]["date"] != today_str:
        points.append({"date": today_str, "time": today_str, "price": inst.current_price, "close": inst.current_price, "open": inst.open_price, "high": inst.high_price, "low": inst.low_price, "volume": inst.volume})

    candles = [{"time": p["time"], "close": p["close"]} for p in points]
    return {"symbol": inst.symbol, "range": range, "data": points, "candles": candles}
