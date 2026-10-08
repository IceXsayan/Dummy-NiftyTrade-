from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Order, Holding
from app.services.order_service import place_order, cancel_order

def test_market_buy_execution_and_funds_deduction(test_db):
    user = test_db.query(User).filter(User.username == "demo1").first()
    inst = test_db.query(Instrument).filter(Instrument.symbol == "INFY").first()
    
    initial_funds = user.available_funds
    qty = 5
    expected_cost = round(qty * inst.current_price, 2)

    success, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol="INFY",
        transaction_type="BUY",
        order_type="MARKET",
        product_type="CNC",
        quantity=qty
    )

    assert success is True
    assert order.status == "EXECUTED"
    assert round(user.available_funds, 2) == round(initial_funds - expected_cost, 2)

def test_insufficient_funds_rejection(test_db):
    user = test_db.query(User).filter(User.username == "demo1").first()
    # Try buying huge quantity exceeding available funds
    success, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol="RELIANCE",
        transaction_type="BUY",
        order_type="MARKET",
        product_type="CNC",
        quantity=100000 # ~29 Crore rupees
    )

    assert success is False
    assert "Insufficient funds" in msg
    assert order.status == "REJECTED"

def test_insufficient_holdings_rejection_for_sell(test_db):
    user = test_db.query(User).filter(User.username == "demo1").first()
    # Attempt to sell more than owned
    success, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol="MRF" if test_db.query(Instrument).filter(Instrument.symbol == "MRF").first() else "RELIANCE",
        transaction_type="SELL",
        order_type="MARKET",
        product_type="CNC",
        quantity=999999
    )

    assert success is False
    assert "Insufficient holdings" in msg
    assert order.status == "REJECTED"

def test_limit_order_placement_and_cancellation(test_db):
    user = test_db.query(User).filter(User.username == "demo1").first()
    # Place buy limit well below current price
    inst = test_db.query(Instrument).filter(Instrument.symbol == "TCS").first()
    limit_price = round(inst.current_price * 0.7, 2)

    funds_before = user.available_funds
    success, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol="TCS",
        transaction_type="BUY",
        order_type="LIMIT",
        product_type="CNC",
        quantity=2,
        price=limit_price
    )

    assert success is True
    assert order.status == "OPEN"
    # Funds should be blocked for limit price
    assert round(user.available_funds, 2) == round(funds_before - (2 * limit_price), 2)

    # Now cancel the order
    cancel_success, cancel_msg = cancel_order(test_db, user.id, order.order_id)
    assert cancel_success is True
    assert order.status == "CANCELLED"
    # Funds refunded
    assert round(user.available_funds, 2) == round(funds_before, 2)
