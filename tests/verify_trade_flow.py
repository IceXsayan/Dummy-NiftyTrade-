"""
Verification Script for NiftyTrade Buy/Sell Flow (Parts D.1 - D.6)
"""
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def run_verification():
    print("=" * 60)
    print("STARTING END-TO-END VERIFICATION OF NIFTYTRADE BUY/SELL FLOW")
    print("=" * 60)

    s = requests.Session()

    # Step 0: Login as demo1
    print("\n[Step 0] Logging in as demo1...")
    login_resp = s.post(f"{BASE_URL}/login", data={"username": "demo1", "password": "demo123"}, allow_redirects=False)
    assert login_resp.status_code == 303, f"Expected 303, got {login_resp.status_code}"
    print("✓ Successfully logged in as demo1 (Session cookie obtained)")

    # Fetch initial context for TCS
    ctx0 = s.get(f"{BASE_URL}/api/ui/order-context?symbol=TCS").json()
    assert ctx0["status"] == "success"
    initial_funds = ctx0["available_funds"]
    initial_qty = ctx0["holding_qty"]
    print(f"  Initial State -> Available Funds: ₹{initial_funds:,.2f} | TCS Holdings: {initial_qty} shares | LTP: ₹{ctx0['ltp']:,.2f}")

    # Step 1: BUY 5 shares of TCS (MARKET, CNC)
    print("\n[Step 1] Buying 5 shares of TCS (MARKET, CNC)...")
    buy_payload = {
        "symbol": "TCS",
        "transaction_type": "BUY",
        "order_type": "MARKET",
        "product_type": "CNC",
        "quantity": 5
    }
    buy_resp = s.post(f"{BASE_URL}/order/place", json=buy_payload)
    print(f"  Response ({buy_resp.status_code}):", buy_resp.json())
    assert buy_resp.status_code == 200, f"Expected 200, got {buy_resp.status_code}"
    buy_data = buy_resp.json()
    assert buy_data["status"] == "success"
    assert "executed" in buy_data["message"].lower()

    # Verify context after BUY
    ctx1 = s.get(f"{BASE_URL}/api/ui/order-context?symbol=TCS").json()
    print(f"  After BUY 5 -> Available Funds: ₹{ctx1['available_funds']:,.2f} | TCS Holdings: {ctx1['holding_qty']} shares")
    assert ctx1["holding_qty"] == initial_qty + 5, f"Expected {initial_qty + 5}, got {ctx1['holding_qty']}"
    assert ctx1["available_funds"] < initial_funds, "Funds should have decreased after BUY"
    print(f"✓ Verification 1 PASSED: Funds went down by ₹{initial_funds - ctx1['available_funds']:,.2f}, holding quantity increased from {initial_qty} to {ctx1['holding_qty']}")

    # Step 2: SELL 2 shares of TCS (MARKET, CNC)
    print("\n[Step 2] Selling 2 shares of TCS (MARKET, CNC)...")
    sell_payload = {
        "symbol": "TCS",
        "transaction_type": "SELL",
        "order_type": "MARKET",
        "product_type": "CNC",
        "quantity": 2
    }
    sell_resp = s.post(f"{BASE_URL}/order/place", json=sell_payload)
    print(f"  Response ({sell_resp.status_code}):", sell_resp.json())
    assert sell_resp.status_code == 200, f"Expected 200, got {sell_resp.status_code}"
    sell_data = sell_resp.json()
    assert sell_data["status"] == "success"
    assert "executed" in sell_data["message"].lower()

    # Verify context after SELL
    ctx2 = s.get(f"{BASE_URL}/api/ui/order-context?symbol=TCS").json()
    print(f"  After SELL 2 -> Available Funds: ₹{ctx2['available_funds']:,.2f} | TCS Holdings: {ctx2['holding_qty']} shares")
    assert ctx2["holding_qty"] == ctx1["holding_qty"] - 2, f"Expected {ctx1['holding_qty'] - 2}, got {ctx2['holding_qty']}"
    assert ctx2["available_funds"] > ctx1["available_funds"], "Funds should have increased after SELL"
    print(f"✓ Verification 2 PASSED: Funds went up by ₹{ctx2['available_funds'] - ctx1['available_funds']:,.2f}, holding quantity decreased from {ctx1['holding_qty']} to {ctx2['holding_qty']}")

    # Step 3: Try to SELL more than owned
    print("\n[Step 3] Attempting to SELL more than owned (e.g., 99999 shares)...")
    oversell_payload = {
        "symbol": "TCS",
        "transaction_type": "SELL",
        "order_type": "MARKET",
        "product_type": "CNC",
        "quantity": 99999
    }
    oversell_resp = s.post(f"{BASE_URL}/order/place", json=oversell_payload)
    print(f"  Response ({oversell_resp.status_code}):", oversell_resp.json())
    assert oversell_resp.status_code == 400, f"Expected 400, got {oversell_resp.status_code}"
    oversell_data = oversell_resp.json()
    assert oversell_data["status"] == "error"
    assert "insufficient holdings" in oversell_data["message"].lower()
    print(f"✓ Verification 3 PASSED: Order rejected with clear message: '{oversell_data['message']}'")

    # Step 4: Try to BUY more than funds allow
    print("\n[Step 4] Attempting to BUY more than funds allow (e.g., 500,000 shares of RELIANCE)...")
    overbuy_payload = {
        "symbol": "RELIANCE",
        "transaction_type": "BUY",
        "order_type": "MARKET",
        "product_type": "CNC",
        "quantity": 500000
    }
    overbuy_resp = s.post(f"{BASE_URL}/order/place", json=overbuy_payload)
    print(f"  Response ({overbuy_resp.status_code}):", overbuy_resp.json())
    assert overbuy_resp.status_code == 400, f"Expected 400, got {overbuy_resp.status_code}"
    overbuy_data = overbuy_resp.json()
    assert overbuy_data["status"] == "error"
    assert "insufficient funds" in overbuy_data["message"].lower()
    print(f"✓ Verification 4 PASSED: Order rejected with clear message: '{overbuy_data['message']}'")

    # Step 5: Place a LIMIT BUY below current price and test Cancel
    print("\n[Step 5] Placing a LIMIT BUY order below current price (TCS @ 70% of LTP)...")
    ltp = ctx2["ltp"]
    limit_price = round(ltp * 0.7, 2)
    limit_qty = 2
    funds_before_limit = ctx2["available_funds"]

    limit_payload = {
        "symbol": "TCS",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "product_type": "CNC",
        "quantity": limit_qty,
        "price": limit_price
    }
    limit_resp = s.post(f"{BASE_URL}/order/place", json=limit_payload)
    print(f"  Limit Order Response ({limit_resp.status_code}):", limit_resp.json())
    assert limit_resp.status_code == 200, f"Expected 200, got {limit_resp.status_code}"
    limit_data = limit_resp.json()
    assert limit_data["status"] == "success"
    order_id = limit_data["order_id"]
    print(f"  Order placed with ID: {order_id}")

    # Check order status in orders page
    ctx_limit = s.get(f"{BASE_URL}/api/ui/order-context?symbol=TCS").json()
    expected_blocked = round(limit_qty * limit_price, 2)
    print(f"  Funds after Limit Order: ₹{ctx_limit['available_funds']:,.2f} (Blocked ₹{expected_blocked:,.2f})")
    assert round(ctx_limit["available_funds"], 2) == round(funds_before_limit - expected_blocked, 2), "Limit buy should block required funds"

    # Now cancel the order
    print(f"  Cancelling order {order_id}...")
    cancel_resp = s.post(f"{BASE_URL}/orders/cancel/{order_id}", allow_redirects=False)
    assert cancel_resp.status_code == 303, f"Expected 303, got {cancel_resp.status_code}"

    # Verify funds refunded after cancellation
    ctx_after_cancel = s.get(f"{BASE_URL}/api/ui/order-context?symbol=TCS").json()
    print(f"  Funds after Cancel: ₹{ctx_after_cancel['available_funds']:,.2f}")
    assert round(ctx_after_cancel["available_funds"], 2) == round(funds_before_limit, 2), "Funds should be fully refunded after order cancellation"
    print("✓ Verification 5 PASSED: LIMIT BUY queued as OPEN with funds blocked, and funds fully refunded upon Cancel!")

    # Step 6: Verify /api/v1/holdings via OAuth flow
    print("\n[Step 6] Testing OAuth Flow & /api/v1/holdings endpoint...")
    from app.core.database import SessionLocal
    from app.models.user import User
    from app.services.oauth_service import create_authorization_code

    db = SessionLocal()
    try:
        user_obj = db.query(User).filter(User.username == "demo1").first()
        auth_code = create_authorization_code(
            db=db,
            client_id="aggregator-app",
            user_id=user_obj.id,
            redirect_uri="http://localhost:3000/callback"
        )
    finally:
        db.close()

    # Exchange auth_code for token
    token_resp = requests.post(f"{BASE_URL}/oauth/token", data={
        "client_id": "aggregator-app",
        "client_secret": "demo-secret",
        "code": auth_code,
        "redirect_uri": "http://localhost:3000/callback"
    })
    assert token_resp.status_code == 200, f"Token endpoint failed: {token_resp.text}"
    token_json = token_resp.json()
    access_token = token_json["access_token"]
    print(f"  Obtained OAuth Bearer Token: {access_token[:20]}...")

    # Fetch holdings via API v1
    v1_resp = requests.get(f"{BASE_URL}/api/v1/holdings", headers={"Authorization": f"Bearer {access_token}"})
    assert v1_resp.status_code == 200, f"API v1 holdings failed: {v1_resp.text}"
    v1_data = v1_resp.json()
    assert v1_data["status"] == "success"
    holdings_list = v1_data["data"]
    
    # Locate TCS in holdings
    tcs_holding = next((h for h in holdings_list if h["symbol"] == "TCS"), None)
    assert tcs_holding is not None, "TCS holding not found in API response"
    print(f"  /api/v1/holdings TCS Data: Symbol={tcs_holding['symbol']}, Quantity={tcs_holding['quantity']}, AvgPrice=₹{tcs_holding['average_price']}, LTP=₹{tcs_holding['current_price']}")
    assert tcs_holding["quantity"] == ctx2["holding_qty"], f"API returned {tcs_holding['quantity']}, expected {ctx2['holding_qty']}"
    print(f"✓ Verification 6 PASSED: /api/v1/holdings returns valid updated data via OAuth (Quantity = {tcs_holding['quantity']})")

    print("\n" + "=" * 60)
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY! 100% PASSING")
    print("=" * 60)

if __name__ == "__main__":
    run_verification()
