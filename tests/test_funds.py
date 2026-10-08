from app.models.user import User
from app.models.trading import Transaction
from app.services.order_service import place_order

def test_funds_deposit(client, test_db):
    user = test_db.query(User).filter(User.username == "demo2").first()
    initial_funds = user.available_funds
    deposit_amt = 50000.0

    user.available_funds = round(user.available_funds + deposit_amt, 2)
    test_db.add(Transaction(
        user_id=user.id,
        type="DEPOSIT",
        amount=deposit_amt,
        balance_after=user.available_funds,
        description="Test Deposit"
    ))
    test_db.commit()

    assert user.available_funds == round(initial_funds + deposit_amt, 2)

def test_intraday_margin_block(test_db):
    user = test_db.query(User).filter(User.username == "demo2").first()
    initial_cash = user.available_funds
    initial_margin = user.used_margin

    # Place MIS buy order for 10 units of ITC
    success, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol="ITC",
        transaction_type="BUY",
        order_type="MARKET",
        product_type="MIS",
        quantity=10
    )

    assert success is True
    # 20% margin should be blocked
    expected_margin = round(10 * order.price * 0.2, 2)
    assert round(user.used_margin, 2) == round(initial_margin + expected_margin, 2)
    assert round(user.available_funds, 2) == round(initial_cash - expected_margin, 2)
