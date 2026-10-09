import pytest
from app.core.config import settings
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Order, Trade, Position
from app.models.outbox import OutboxEvent
from app.services.order_service import place_order
from app.services.outbox_service import enqueue_outbox_event_in_tx
from app.services.price_simulator import execute_limit_order

import httpx
from unittest.mock import MagicMock, patch

API_KEY = settings.INTERNAL_API_KEY
AUTH_HEADERS = {"x-internal-key": API_KEY}

@pytest.fixture(autouse=True)
def mock_outbox_delivery():
    with patch("app.services.outbox_service.trigger_single_event_delivery", return_value=None) as m:
        yield m

def test_new_google_user_via_provisioning_has_zero_holdings(client, test_db):
    """
    Requirement 5: A new Google user via provisioning has zero holdings,
    profile, shared-identity, starting funds, and ZERO orders/trades/positions.
    """
    email = "newgoogleuser@tradeone.org"
    resp = client.post(
        "/internal/v1/users/provision",
        json={"email": email, "full_name": "New Google User"},
        headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    user_data = resp.json()["data"]
    assert user_data["email"] == email

    user = test_db.query(User).filter(User.email == email).first()
    assert user is not None
    assert user.available_funds == settings.STARTING_FUNDS
    assert user.used_margin == 0.0

    # ZERO holdings, positions, orders, trades
    assert test_db.query(Holding).filter(Holding.user_id == user.id).count() == 0
    assert test_db.query(Position).filter(Position.user_id == user.id).count() == 0
    assert test_db.query(Order).filter(Order.user_id == user.id).count() == 0
    assert test_db.query(Trade).filter(Trade.user_id == user.id).count() == 0

    # Internal holdings endpoint returns empty list with totals 0
    h_resp = client.get(f"/internal/v1/users/{email}/holdings", headers=AUTH_HEADERS)
    assert h_resp.status_code == 200
    h_json = h_resp.json()
    assert h_json["status"] == "success"
    assert h_json["data"] == []
    assert h_json["totals"]["invested"] == 0.0
    assert h_json["totals"]["current_value"] == 0.0
    assert h_json["totals"]["total_pnl"] == 0.0
    assert h_json["totals"]["count"] == 0

def test_internal_endpoint_returns_empty_list_for_existing_user_without_trades(client, test_db):
    """
    Requirement 5: The internal endpoint returns an empty list (not 404)
    for an existing user without trades.
    """
    email = "notrades_user@tradeone.org"
    prov_resp = client.post(
        "/internal/v1/users/provision",
        json={"email": email, "full_name": "No Trades User"},
        headers=AUTH_HEADERS
    )
    assert prov_resp.status_code == 200

    resp = client.get(f"/internal/v1/users/{email}/holdings", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"
    assert res_data["data"] == []
    assert res_data["totals"]["count"] == 0
    assert res_data["totals"]["invested"] == 0.0

def test_buy_5_and_sell_2_returns_3_with_correct_average_price(client, test_db):
    """
    Requirement 5: After a buy of 5 and a sell of 2 it returns 3 with the correct average price.
    """
    email = "trader_alice@tradeone.org"
    client.post("/internal/v1/users/provision", json={"email": email, "full_name": "Alice Trader"}, headers=AUTH_HEADERS)
    user = test_db.query(User).filter(User.email == email).first()

    inst = test_db.query(Instrument).filter(Instrument.symbol == "TCS").first()
    assert inst is not None

    # Step 1: BUY 5
    buy_ok, buy_msg, buy_order = place_order(
        db=test_db,
        user_id=user.id,
        symbol=inst.symbol,
        transaction_type="BUY",
        order_type="MARKET",
        product_type="CNC",
        quantity=5
    )
    assert buy_ok is True
    test_db.refresh(user)

    # Verify holdings after buy of 5
    h_resp1 = client.get(f"/internal/v1/users/{email}/holdings", headers=AUTH_HEADERS)
    assert h_resp1.status_code == 200
    h1_data = h_resp1.json()["data"]
    assert len(h1_data) == 1
    assert h1_data[0]["tradingsymbol"] == "TCS"
    assert h1_data[0]["quantity"] == 5
    expected_avg = h1_data[0]["average_price"]

    # Step 2: SELL 2
    sell_ok, sell_msg, sell_order = place_order(
        db=test_db,
        user_id=user.id,
        symbol=inst.symbol,
        transaction_type="SELL",
        order_type="MARKET",
        product_type="CNC",
        quantity=2
    )
    assert sell_ok is True
    test_db.refresh(user)

    # Verify holdings after sell of 2: net 3 shares with same average price
    h_resp2 = client.get(f"/internal/v1/users/{email}/holdings", headers=AUTH_HEADERS)
    assert h_resp2.status_code == 200
    h2_data = h_resp2.json()["data"]
    assert len(h2_data) == 1
    assert h2_data[0]["tradingsymbol"] == "TCS"
    assert h2_data[0]["quantity"] == 3
    assert h2_data[0]["average_price"] == expected_avg

def test_two_different_emails_never_see_each_others_data(client, test_db):
    """
    Requirement 5: Two different emails never see each other's data.
    """
    email_a = "user_alpha@tradeone.org"
    email_b = "user_beta@tradeone.org"

    client.post("/internal/v1/users/provision", json={"email": email_a}, headers=AUTH_HEADERS)
    client.post("/internal/v1/users/provision", json={"email": email_b}, headers=AUTH_HEADERS)

    user_a = test_db.query(User).filter(User.email == email_a).first()
    user_b = test_db.query(User).filter(User.email == email_b).first()

    # User A buys RELIANCE
    place_order(test_db, user_a.id, "RELIANCE", "BUY", "MARKET", "CNC", 4)
    # User B buys INFY
    place_order(test_db, user_b.id, "INFY", "BUY", "MARKET", "CNC", 8)

    resp_a = client.get(f"/internal/v1/users/{email_a}/holdings", headers=AUTH_HEADERS)
    assert resp_a.status_code == 200
    data_a = resp_a.json()["data"]
    syms_a = [h["tradingsymbol"] for h in data_a]
    assert "RELIANCE" in syms_a
    assert "INFY" not in syms_a

    resp_b = client.get(f"/internal/v1/users/{email_b}/holdings", headers=AUTH_HEADERS)
    assert resp_b.status_code == 200
    data_b = resp_b.json()["data"]
    syms_b = [h["tradingsymbol"] for h in data_b]
    assert "INFY" in syms_b
    assert "RELIANCE" not in syms_b

def test_unknown_email_returns_404_and_never_the_demo_user(client, test_db):
    """
    Requirement 5: Unknown email returns 404 and never the demo user.
    """
    unknown_email = "completely_unknown_user_404@nowhere.com"
    resp = client.get(f"/internal/v1/users/{unknown_email}/holdings", headers=AUTH_HEADERS)
    assert resp.status_code == 404
    assert "USER_NOT_FOUND" in resp.text

    summary_resp = client.get(f"/internal/v1/users/{unknown_email}/summary", headers=AUTH_HEADERS)
    assert summary_resp.status_code == 404
    assert "USER_NOT_FOUND" in summary_resp.text

def test_pending_limit_orders_do_not_appear_as_holdings(client, test_db):
    """
    Requirement 5: Pending limit orders do not appear as holdings.
    """
    email = "limit_test_user@tradeone.org"
    client.post("/internal/v1/users/provision", json={"email": email}, headers=AUTH_HEADERS)
    user = test_db.query(User).filter(User.email == email).first()

    inst = test_db.query(Instrument).filter(Instrument.symbol == "RELIANCE").first()
    # Place Limit order far below market price so it cannot execute immediately
    low_limit_price = 100.0
    ok, msg, order = place_order(
        db=test_db,
        user_id=user.id,
        symbol=inst.symbol,
        transaction_type="BUY",
        order_type="LIMIT",
        product_type="CNC",
        quantity=5,
        price=low_limit_price
    )
    assert ok is True
    assert order.status == "OPEN"

    # Call holdings endpoint: should be empty list
    resp = client.get(f"/internal/v1/users/{email}/holdings", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["data"] == []

def test_outbox_event_created_in_same_transaction_as_trade(test_db):
    """
    Requirement 5: The outbox event is created in the same transaction as the trade.
    """
    email = "tx_outbox_trader@tradeone.org"
    user = User(
        username="tx_user",
        email=email,
        full_name="TX User",
        hashed_password="pw",
        client_id="NTTX1",
        masked_pan="TXPAN1111A",
        masked_demat="IN30000100000000",
        mobile="9111122222",
        available_funds=1000000.0
    )
    test_db.add(user)
    test_db.commit()

    inst = test_db.query(Instrument).filter(Instrument.symbol == "HDFCBANK").first()

    # Clear prior outbox events for this user if any
    test_db.query(OutboxEvent).filter(OutboxEvent.email == email).delete()
    test_db.commit()

    # Execute trade
    ok, msg, ord_obj = place_order(
        db=test_db,
        user_id=user.id,
        symbol=inst.symbol,
        transaction_type="BUY",
        order_type="MARKET",
        product_type="CNC",
        quantity=3
    )
    assert ok is True

    # Verify OutboxEvent exists in DB
    ev = test_db.query(OutboxEvent).filter(OutboxEvent.email == email).first()
    assert ev is not None
    assert ev.event == "HOLDINGS_CHANGED"
    assert ev.provider == settings.PROVIDER_CODE
    assert ev.status in ("PENDING", "SENT")

def test_summary_endpoint_contract(client, test_db):
    """
    Requirement 2: GET /internal/v1/users/{email}/summary returns invested,
    current value, day change, holding count, as_of, and timestamp of last executed trade.
    """
    email = "summary_contract_user@tradeone.org"
    client.post("/internal/v1/users/provision", json={"email": email}, headers=AUTH_HEADERS)
    user = test_db.query(User).filter(User.email == email).first()

    # Summary with no trades
    resp0 = client.get(f"/internal/v1/users/{email}/summary", headers=AUTH_HEADERS)
    assert resp0.status_code == 200
    s0 = resp0.json()["data"]
    assert s0["invested"] == 0.0
    assert s0["current_value"] == 0.0
    assert s0["day_change"] == 0.0
    assert s0["holding_count"] == 0
    assert s0["as_of"] is not None
    assert s0["last_executed_trade_at"] is None

    # Execute trade
    place_order(test_db, user.id, "SBIN", "BUY", "MARKET", "CNC", 10)

    # Summary with trade
    resp1 = client.get(f"/internal/v1/users/{email}/summary", headers=AUTH_HEADERS)
    assert resp1.status_code == 200
    s1 = resp1.json()["data"]
    assert s1["holding_count"] == 1
    assert s1["invested"] > 0
    assert s1["current_value"] > 0
    assert s1["last_executed_trade_at"] is not None
