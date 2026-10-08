import random
from datetime import datetime, timezone
from typing import Tuple, Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Order, Trade, Holding, Position, Transaction
from app.services.price_simulator import is_market_open, execute_limit_order

def place_order(
    db: Session,
    user_id: int,
    symbol: str,
    transaction_type: str, # BUY / SELL
    order_type: str,       # MARKET / LIMIT
    product_type: str,     # CNC / MIS
    quantity: int,
    price: Optional[float] = None
) -> Tuple[bool, str, Optional[Order]]:
    """
    Validates, deducts funds / margin, checks holdings, and places order.
    Returns (success: bool, message: str, order: Optional[Order]).
    """
    if quantity <= 0:
        return False, "Quantity must be greater than zero", None

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False, "User not found", None

    inst = db.query(Instrument).filter(Instrument.symbol == symbol.upper()).first()
    if not inst:
        return False, f"Instrument {symbol} not found", None

    market_open = is_market_open(db)
    req_price = price if (order_type == "LIMIT" and price and price > 0) else inst.current_price

    total_value = round(quantity * req_price, 2)
    order_id = f"ORD-{int(datetime.now(timezone.utc).replace(tzinfo=None).timestamp())}-{random.randint(1000, 9999)}"

    # Validate based on Product Type and Transaction Type
    if product_type == "CNC":
        # DELIVERY
        if transaction_type == "BUY":
            if user.available_funds < total_value:
                # Reject order
                rej_ord = Order(
                    order_id=order_id,
                    user_id=user.id,
                    instrument_id=inst.id,
                    transaction_type="BUY",
                    order_type=order_type,
                    product_type="CNC",
                    quantity=quantity,
                    price=req_price,
                    status="REJECTED",
                    rejection_reason=f"Insufficient funds: required ₹{total_value:,.2f}, available ₹{user.available_funds:,.2f}",
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                )
                db.add(rej_ord)
                db.commit()
                return False, f"Insufficient funds. Required ₹{total_value:,.2f}, but available is ₹{user.available_funds:,.2f}", rej_ord

            # Deduct funds
            user.available_funds = round(user.available_funds - total_value, 2)
            if order_type == "LIMIT":
                db.add(Transaction(
                    user_id=user.id,
                    type="MARGIN_BLOCK",
                    amount=total_value,
                    balance_after=user.available_funds,
                    description=f"Margin blocked for Limit Buy: {quantity} {inst.symbol} @ ₹{req_price}",
                    reference_id=order_id
                ))
            elif not market_open:
                db.add(Transaction(
                    user_id=user.id,
                    type="MARGIN_BLOCK",
                    amount=total_value,
                    balance_after=user.available_funds,
                    description=f"Margin blocked for AMO Buy: {quantity} {inst.symbol} @ ₹{req_price}",
                    reference_id=order_id
                ))

        elif transaction_type == "SELL":
            holding = db.query(Holding).filter(
                Holding.user_id == user.id,
                Holding.instrument_id == inst.id
            ).first()
            if not holding or holding.quantity < quantity:
                avail_qty = holding.quantity if holding else 0
                rej_ord = Order(
                    order_id=order_id,
                    user_id=user.id,
                    instrument_id=inst.id,
                    transaction_type="SELL",
                    order_type=order_type,
                    product_type="CNC",
                    quantity=quantity,
                    price=req_price,
                    status="REJECTED",
                    rejection_reason=f"Insufficient holdings: requested {quantity} units, available {avail_qty} units",
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                )
                db.add(rej_ord)
                db.commit()
                return False, f"Insufficient holdings. Available: {avail_qty}, requested: {quantity}", rej_ord

    elif product_type == "MIS":
        # Check if this order is closing an existing open position
        pos = db.query(Position).filter(
            Position.user_id == user.id,
            Position.instrument_id == inst.id,
            Position.product_type == "MIS"
        ).first()
        is_closing = False
        if pos and pos.quantity != 0:
            if (pos.quantity > 0 and transaction_type == "SELL") or (pos.quantity < 0 and transaction_type == "BUY"):
                is_closing = True

        margin_required = round(total_value * 0.2, 2)
        if not is_closing:
            if user.available_funds < margin_required:
                rej_ord = Order(
                    order_id=order_id,
                    user_id=user.id,
                    instrument_id=inst.id,
                    transaction_type=transaction_type,
                    order_type=order_type,
                    product_type="MIS",
                    quantity=quantity,
                    price=req_price,
                    status="REJECTED",
                    rejection_reason=f"Insufficient margin: required ₹{margin_required:,.2f}, available ₹{user.available_funds:,.2f}",
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                )
                db.add(rej_ord)
                db.commit()
                return False, f"Insufficient margin: required ₹{margin_required:,.2f}, available ₹{user.available_funds:,.2f}", rej_ord

            # Block margin
            user.available_funds = round(user.available_funds - margin_required, 2)
            user.used_margin = round(user.used_margin + margin_required, 2)

    # Create Order object
    order = Order(
        order_id=order_id,
        user_id=user.id,
        instrument_id=inst.id,
        transaction_type=transaction_type,
        order_type=order_type,
        product_type=product_type,
        quantity=quantity,
        price=req_price,
        status="OPEN",
        created_at=datetime.now(timezone.utc).replace(tzinfo=None)
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Execution logic:
    # 1. If MARKET order:
    #    - If market is OPEN: execute immediately at current_price!
    #    - If market is CLOSED: keep as OPEN (queued AMO)
    # 2. If LIMIT order:
    #    - If market is OPEN and limit condition immediately satisfied: execute immediately!
    #    - Otherwise remains OPEN
    if market_open:
        if order_type == "MARKET":
            execute_limit_order(db, order, inst.current_price)
            return True, f"Market order {order.order_id} executed at ₹{inst.current_price:,.2f}", order
        elif order_type == "LIMIT":
            if (transaction_type == "BUY" and inst.current_price <= req_price) or \
               (transaction_type == "SELL" and inst.current_price >= req_price):
                execute_limit_order(db, order, inst.current_price)
                return True, f"Limit order {order.order_id} executed immediately at ₹{inst.current_price:,.2f}", order
            else:
                return True, f"Limit order {order.order_id} placed successfully and queued in Order Book", order
    else:
        return True, f"Market is currently closed. Order {order.order_id} queued as AMO (After Market Order)", order

def cancel_order(db: Session, user_id: int, order_id_str: str) -> Tuple[bool, str]:
    order = db.query(Order).filter(
        Order.order_id == order_id_str,
        Order.user_id == user_id
    ).first()
    if not order:
        return False, "Order not found"
    if order.status != "OPEN":
        return False, f"Cannot cancel order in status: {order.status}"

    user = db.query(User).filter(User.id == user_id).first()
    # Refund reserved funds / margin
    if order.product_type == "CNC" and order.transaction_type == "BUY":
        reserved = round(order.quantity * order.price, 2)
        user.available_funds = round(user.available_funds + reserved, 2)
        db.add(Transaction(
            user_id=user.id,
            type="DEPOSIT",
            amount=reserved,
            balance_after=user.available_funds,
            description=f"Refund for cancelled order {order.order_id}",
            reference_id=order.order_id
        ))
    elif order.product_type == "MIS":
        margin = round(order.quantity * order.price * 0.2, 2)
        user.available_funds = round(user.available_funds + margin, 2)
        user.used_margin = max(0.0, round(user.used_margin - margin, 2))

    order.status = "CANCELLED"
    db.commit()
    return True, f"Order {order.order_id} cancelled successfully"

def square_off_position(db: Session, user_id: int, position_id: int) -> Tuple[bool, str]:
    pos = db.query(Position).filter(Position.id == position_id, Position.user_id == user_id).first()
    if not pos or not pos.is_open or pos.quantity == 0:
        return False, "Active open position not found"

    inst = pos.instrument
    side = "SELL" if pos.quantity > 0 else "BUY"
    qty = abs(pos.quantity)

    success, msg, _ = place_order(
        db=db,
        user_id=user_id,
        symbol=inst.symbol,
        transaction_type=side,
        order_type="MARKET",
        product_type="MIS",
        quantity=qty
    )
    return success, msg
