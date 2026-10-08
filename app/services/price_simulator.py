import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.instrument import Instrument
from app.models.trading import Order, Trade, Holding, Position, Transaction
from app.models.user import User
from app.models.system import SystemConfig

# Global in-memory broadcast queue for SSE subscribers
_subscribers: List[asyncio.Queue] = []

# Index trackers
market_indices: Dict[str, Dict[str, float]] = {
    "NIFTY 50": {"current": 24850.40, "prev_close": 24780.00, "open": 24800.00, "high": 24920.00, "low": 24760.00},
    "SENSEX": {"current": 81650.25, "prev_close": 81400.00, "open": 81450.00, "high": 81820.00, "low": 81380.00},
    "BANK NIFTY": {"current": 51420.80, "prev_close": 51200.00, "open": 51250.00, "high": 51600.00, "low": 51100.00},
}

def register_subscriber() -> asyncio.Queue:
    q = asyncio.Queue(maxsize=50)
    _subscribers.append(q)
    return q

def unregister_subscriber(q: asyncio.Queue):
    if q in _subscribers:
        _subscribers.remove(q)

async def broadcast_tick(data: Dict[str, Any]):
    dead_queues = []
    for q in _subscribers:
        try:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(data)
        except Exception:
            dead_queues.append(q)
    for dq in dead_queues:
        if dq in _subscribers:
            _subscribers.remove(dq)

def is_market_open(db: Session) -> bool:
    cfg = db.query(SystemConfig).filter(SystemConfig.key == "market_open").first()
    return cfg.value.lower() == "true" if cfg else True

def execute_limit_order(db: Session, order: Order, execution_price: float):
    """Executes a matching limit order and updates holdings/positions/funds/trades."""
    user = db.query(User).filter(User.id == order.user_id).first()
    inst = db.query(Instrument).filter(Instrument.id == order.instrument_id).first()
    if not user or not inst:
        return

    trade_val = round(order.quantity * execution_price, 2)

    if order.product_type == "CNC":
        # Delivery
        holding = db.query(Holding).filter(
            Holding.user_id == user.id,
            Holding.instrument_id == inst.id
        ).first()

        if order.transaction_type == "BUY":
            order_type_label = "Market" if order.order_type == "MARKET" else "Limit"
            reserved = round(order.quantity * order.price, 2)
            refund = max(0.0, reserved - trade_val)
            user.available_funds = round(user.available_funds + refund, 2)

            if holding:
                new_qty = holding.quantity + order.quantity
                new_avg = ((holding.quantity * holding.average_price) + trade_val) / new_qty
                holding.quantity = new_qty
                holding.average_price = round(new_avg, 2)
            else:
                db.add(Holding(
                    user_id=user.id,
                    instrument_id=inst.id,
                    quantity=order.quantity,
                    average_price=execution_price
                ))

            db.add(Transaction(
                user_id=user.id,
                type="TRADE_DEBIT",
                amount=trade_val,
                balance_after=round(user.available_funds, 2),
                description=f"{order_type_label} Order Executed: Bought {order.quantity} {inst.symbol} @ ₹{execution_price:,.2f}",
                reference_id=order.order_id
            ))
        else:
            # SELL
            order_type_label = "Market" if order.order_type == "MARKET" else "Limit"
            if holding:
                holding.quantity = max(0, holding.quantity - order.quantity)
                if holding.quantity == 0:
                    db.delete(holding)
            user.available_funds = round(user.available_funds + trade_val, 2)
            db.add(Transaction(
                user_id=user.id,
                type="TRADE_CREDIT",
                amount=trade_val,
                balance_after=round(user.available_funds, 2),
                description=f"{order_type_label} Order Executed: Sold {order.quantity} {inst.symbol} @ ₹{execution_price:,.2f}",
                reference_id=order.order_id
            ))
    else:
        # Intraday MIS
        pos = db.query(Position).filter(
            Position.user_id == user.id,
            Position.instrument_id == inst.id,
            Position.product_type == "MIS"
        ).first()
        if not pos:
            pos = Position(
                user_id=user.id,
                instrument_id=inst.id,
                product_type="MIS",
                quantity=0,
                buy_quantity=0,
                sell_quantity=0,
                buy_value=0.0,
                sell_value=0.0,
                is_open=True
            )
            db.add(pos)

        if order.transaction_type == "BUY":
            pos.quantity += order.quantity
            pos.buy_quantity += order.quantity
            pos.buy_value += trade_val
        else:
            pos.quantity -= order.quantity
            pos.sell_quantity += order.quantity
            pos.sell_value += trade_val

        pos.is_open = (pos.quantity != 0)
        if not pos.is_open:
            # Release blocked margin when position is closed
            margin_req = round(trade_val * 0.2, 2)
            user.available_funds = round(user.available_funds + margin_req, 2)
            user.used_margin = max(0.0, round(user.used_margin - margin_req, 2))

    # Update Order
    order.status = "EXECUTED"
    order.average_executed_price = execution_price
    order.executed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create Trade
    trade_id = f"TRD-{int(datetime.now(timezone.utc).replace(tzinfo=None).timestamp())}-{random.randint(100, 999)}"
    db.add(Trade(
        trade_id=trade_id,
        order_id=order.id,
        user_id=user.id,
        instrument_id=inst.id,
        transaction_type=order.transaction_type,
        product_type=order.product_type,
        quantity=order.quantity,
        price=execution_price,
        trade_time=datetime.now(timezone.utc).replace(tzinfo=None)
    ))
    db.commit()

def _simulate_tick_in_db():
    db = SessionLocal()
    try:
        market_open = is_market_open(db)
        if not market_open:
            return False, [], {}

        instruments = db.query(Instrument).all()
        tick_updates = []
        stock_moves = []

        for inst in instruments:
            # Random walk percentage between -0.4% and +0.4%
            pct_change = random.gauss(0.0001, 0.0025)
            new_price = round(inst.current_price * (1 + pct_change), 2)

            # Circuit limit check (+/- 10% from previous close)
            lower_limit = round(inst.previous_close * (1 - (inst.circuit_limit_pct / 100.0)), 2)
            upper_limit = round(inst.previous_close * (1 + (inst.circuit_limit_pct / 100.0)), 2)

            new_price = max(lower_limit, min(upper_limit, new_price))
            new_volume = inst.volume + random.randint(10, 500)

            inst.current_price = new_price
            inst.volume = new_volume
            if new_price > inst.high_price:
                inst.high_price = new_price
            if new_price < inst.low_price:
                inst.low_price = new_price

            day_change = round(inst.current_price - inst.previous_close, 2)
            day_change_pct = round((day_change / inst.previous_close) * 100, 2) if inst.previous_close else 0.0
            stock_moves.append(pct_change)

            tick_updates.append({
                "symbol": inst.symbol,
                "isin": inst.isin,
                "price": new_price,
                "change": day_change,
                "change_pct": day_change_pct,
                "high": inst.high_price,
                "low": inst.low_price,
                "volume": inst.volume
            })

        # Check and execute matching limit and queued market orders
        open_orders = db.query(Order).filter(Order.status == "OPEN").all()
        for ord_item in open_orders:
            inst = ord_item.instrument
            if ord_item.order_type == "MARKET":
                execute_limit_order(db, ord_item, inst.current_price)
            elif ord_item.transaction_type == "BUY" and inst.current_price <= ord_item.price:
                execute_limit_order(db, ord_item, inst.current_price)
            elif ord_item.transaction_type == "SELL" and inst.current_price >= ord_item.price:
                execute_limit_order(db, ord_item, inst.current_price)

        db.commit()

        # Update Market Indices
        avg_move = sum(stock_moves) / max(len(stock_moves), 1)
        for idx_name, idx_data in market_indices.items():
            noise = random.gauss(0, 0.0008)
            idx_change = avg_move + noise
            idx_data["current"] = round(idx_data["current"] * (1 + idx_change), 2)
            if idx_data["current"] > idx_data["high"]:
                idx_data["high"] = idx_data["current"]
            if idx_data["current"] < idx_data["low"]:
                idx_data["low"] = idx_data["current"]

        indices_snapshot = {
            k: {
                "current": v["current"],
                "change": round(v["current"] - v["prev_close"], 2),
                "change_pct": round(((v["current"] - v["prev_close"]) / v["prev_close"]) * 100, 2),
                "high": v["high"],
                "low": v["low"]
            } for k, v in market_indices.items()
        }
        return True, tick_updates, indices_snapshot
    finally:
        db.close()

async def run_price_simulator():
    """Background task running every 5 seconds to simulate realistic market price movement."""
    print("Starting background Price Simulator...")
    while True:
        try:
            await asyncio.sleep(5)
            market_open, tick_updates, indices_snapshot = await asyncio.to_thread(_simulate_tick_in_db)
            if market_open and tick_updates:
                broadcast_payload = {
                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                    "market_open": True,
                    "indices": indices_snapshot,
                    "ticks": tick_updates
                }
                await broadcast_tick(broadcast_payload)
        except asyncio.CancelledError:
            print("Price simulator task cancelled.")
            break
        except Exception as e:
            print(f"Error in price simulator: {e}")
            await asyncio.sleep(2)
