from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Trade
from app.services.outbox_service import enqueue_outbox_event_in_tx

DEMO_USER_EMAILS = {"demo1@niftytrade.local", "demo2@niftytrade.local"}
DEMO_USERNAMES = {"demo1", "demo2"}

def is_demo_user(user: User) -> bool:
    """Check if a user is one of the original seeded demo users."""
    if not user:
        return False
    return (user.email in DEMO_USER_EMAILS) or (user.username in DEMO_USERNAMES)

def compute_user_delivery_holdings(db: Session, user: User, sync_db: bool = True) -> List[Holding]:
    """
    Computes delivery holdings strictly from the user's real executed trades.
    - Non-demo users get ZERO holdings if they have not made trades.
    - Demo users keep seeded demo data ONLY when DEMO_MODE is true.
    - Excludes open orders and pending limit orders (trades only).
    - Delivery holdings only (Trade.product_type == 'CNC').
    - Quantities net of sells.
    - Average price computed from executed trades.
    - Live prices from the live price engine (Instrument.current_price).
    - Covers all instrument types: equity, reit, invit, bond.
    """
    demo_mode = getattr(settings, "DEMO_MODE", False)
    if is_demo_user(user) and demo_mode:
        return db.query(Holding).filter(Holding.user_id == user.id, Holding.quantity > 0).all()

    # Query all executed delivery trades for this user ordered chronologically
    executed_trades = db.query(Trade).filter(
        Trade.user_id == user.id,
        Trade.product_type == "CNC"
    ).order_by(Trade.trade_time.asc(), Trade.id.asc()).all()

    # If no trades executed, real delivery holdings must be empty
    if not executed_trades:
        if sync_db and not (is_demo_user(user) and demo_mode):
            # Clean up unbacked holdings for this non-demo user
            stale_holdings = db.query(Holding).filter(Holding.user_id == user.id).all()
            for sh in stale_holdings:
                db.delete(sh)
            if stale_holdings:
                db.flush()
        return []

    # Group trades by instrument
    trades_by_inst: Dict[int, List[Trade]] = defaultdict(list)
    for t in executed_trades:
        trades_by_inst[t.instrument_id].append(t)

    real_holdings: List[Holding] = []
    active_instrument_ids = set()

    for inst_id, t_list in trades_by_inst.items():
        inst = db.query(Instrument).filter(Instrument.id == inst_id).first()
        if not inst:
            continue

        net_qty = 0
        total_cost = 0.0
        avg_price = 0.0

        for t in t_list:
            if t.transaction_type == "BUY":
                new_qty = net_qty + t.quantity
                new_cost = total_cost + (t.quantity * t.price)
                net_qty = new_qty
                total_cost = new_cost
                avg_price = total_cost / net_qty if net_qty > 0 else 0.0
            elif t.transaction_type == "SELL":
                net_qty = max(0, net_qty - t.quantity)
                if net_qty == 0:
                    total_cost = 0.0
                    avg_price = 0.0
                else:
                    # When selling, average buy price remains unchanged
                    total_cost = net_qty * avg_price

        if net_qty > 0:
            active_instrument_ids.add(inst_id)
            avg_price_rounded = round(avg_price, 2)

            if sync_db:
                holding = db.query(Holding).filter(
                    Holding.user_id == user.id,
                    Holding.instrument_id == inst_id
                ).first()
                if not holding:
                    holding = Holding(
                        user_id=user.id,
                        instrument_id=inst_id,
                        quantity=net_qty,
                        average_price=avg_price_rounded
                    )
                    db.add(holding)
                    db.flush()
                else:
                    holding.quantity = net_qty
                    holding.average_price = avg_price_rounded
                holding.instrument = inst
                real_holdings.append(holding)
            else:
                # In-memory representation
                dummy_holding = Holding(
                    user_id=user.id,
                    instrument_id=inst_id,
                    quantity=net_qty,
                    average_price=avg_price_rounded
                )
                dummy_holding.instrument = inst
                real_holdings.append(dummy_holding)

    if sync_db and not (is_demo_user(user) and demo_mode):
        # Remove any holdings in DB that no longer have positive net quantity or trades
        stale = db.query(Holding).filter(
            Holding.user_id == user.id,
            ~Holding.instrument_id.in_(active_instrument_ids) if active_instrument_ids else True
        ).all()
        for sh in stale:
            db.delete(sh)
        if stale:
            db.flush()

    return real_holdings

def get_user_summary_data(db: Session, user: User) -> Dict[str, Any]:
    """
    Computes invested, current value, day change, holding count, as_of,
    and the timestamp of the last executed trade for that user.
    """
    holdings = compute_user_delivery_holdings(db, user)

    total_invested = round(sum(h.invested_value for h in holdings), 2)
    total_current = round(sum(h.current_value for h in holdings), 2)
    day_change = round(sum(h.quantity * h.instrument.day_change for h in holdings), 2)
    holding_count = len(holdings)
    as_of = datetime.now(timezone.utc).isoformat()

    last_trade = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.trade_time.desc()).first()
    last_trade_time = last_trade.trade_time.isoformat() if last_trade and last_trade.trade_time else None

    total_pnl = round(total_current - total_invested, 2)
    total_pnl_pct = round((total_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0

    return {
        "user_id": user.client_id,
        "email": user.email,
        "full_name": user.full_name,
        "invested": total_invested,
        "current_value": total_current,
        "day_change": day_change,
        "holding_count": holding_count,
        "as_of": as_of,
        "last_executed_trade_at": last_trade_time,
        "last_trade_time": last_trade_time,
        # Standard envelope & parity fields
        "available_funds": user.available_funds,
        "used_margin": user.used_margin,
        "net_worth": round(user.available_funds + total_current + user.used_margin, 2),
        "total_invested": total_invested,
        "total_current": total_current,
        "total_pnl": total_pnl,
        "total_pnl_percentage": total_pnl_pct,
        "day_pnl": day_change,
        "holdings_count": holding_count,
        "provider": getattr(settings, "PROVIDER_CODE", "a"),
        "broker_name": getattr(settings, "BROKER_NAME", "NiftyTrade")
    }

def find_unbacked_holdings(db: Session, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Finds holdings that have no executed trades backing them.
    Returns list of dicts with details.
    """
    query = db.query(Holding)
    if user_id:
        query = query.filter(Holding.user_id == user_id)

    holdings = query.all()
    unbacked = []

    for h in holdings:
        # Check if there are any executed buy trades for this user and instrument
        trade_count = db.query(Trade).filter(
            Trade.user_id == h.user_id,
            Trade.instrument_id == h.instrument_id,
            Trade.product_type == "CNC",
            Trade.transaction_type == "BUY"
        ).count()

        if trade_count == 0:
            unbacked.append({
                "holding_id": h.id,
                "user_id": h.user_id,
                "user_email": h.user.email if h.user else "Unknown",
                "client_id": h.user.client_id if h.user else "Unknown",
                "username": h.user.username if h.user else "Unknown",
                "symbol": h.instrument.symbol if h.instrument else "Unknown",
                "quantity": h.quantity,
                "average_price": h.average_price,
                "holding_obj": h
            })

    return unbacked

def purge_unbacked_holdings(db: Session, user_id: Optional[int] = None) -> Tuple[int, List[str]]:
    """
    Deletes unbacked holdings and enqueues a HOLDINGS_CHANGED outbox event
    for each affected user in the same transaction. Real executed trades are never touched.
    Returns (count_deleted, affected_emails).
    """
    unbacked = find_unbacked_holdings(db, user_id=user_id)
    if not unbacked:
        return 0, []

    affected_emails = set()
    count = 0

    for item in unbacked:
        h = item["holding_obj"]
        email = item["user_email"]
        if email and email != "Unknown":
            affected_emails.add(email)
        db.delete(h)
        count += 1

    db.flush()

    # Fire HOLDINGS_CHANGED event for each affected user in the same transaction
    for email in affected_emails:
        enqueue_outbox_event_in_tx(db, email, event_type="HOLDINGS_CHANGED")

    return count, list(affected_emails)
