import re
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import httpx

from app.core.config import settings
from app.models.user import User
from app.models.trading import Holding
from app.models.outbox import OutboxEvent
from app.models.instrument import Instrument
from app.shared_identity import normalize_email, generate_identity
from app.services.portfolio_starter import generate_starter_portfolio, load_shared_instruments
from app.services.outbox_service import enqueue_outbox_event, post_event_with_retry
from app.routers.internal_api import reset_rate_limiter
from app.services.oauth_service import create_authorization_code

API_KEY = "tradeone-internal-secret-key"

# 1. Identity Consistency
def test_identity_consistency():
    email = "trader.sam@example.com"
    id1 = generate_identity(email)
    id2 = generate_identity(email)
    
    assert id1 == id2
    assert id1["email"] == email
    assert id1["client_id"] == id2["client_id"]
    assert id1["masked_pan"] == id2["masked_pan"]
    assert id1["masked_aadhaar"] == id2["masked_aadhaar"]
    assert id1["mobile"] == id2["mobile"]

    # Full name derivation when claim not provided
    assert id1["full_name"] == "Trader Sam"

    # Full name derivation when Google name claim provided
    id_google = generate_identity(email, full_name="Samantha Ray")
    assert id_google["full_name"] == "Samantha Ray"
    assert id_google["client_id"] == id1["client_id"]

    # Never generate real-looking Aadhaar/PAN data
    # Real PAN format: 5 letters, 4 digits, 1 letter: ^[A-Z]{5}[0-9]{4}[A-Z]$
    pan = id1["pan"]
    real_pan_pattern = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    assert not real_pan_pattern.match(pan)
    assert pan.startswith("TEST-PAN-")

    # Real Aadhaar format: 12 valid digits
    aadhaar = id1["aadhaar"]
    real_aadhaar_pattern = re.compile(r"^\d{12}$")
    assert not real_aadhaar_pattern.match(aadhaar)
    assert aadhaar.startswith("0000-0000-")

# 2. Email Normalization
def test_email_normalization():
    assert normalize_email("  User.Test@Example.COM  ") == "user.test@example.com"
    assert normalize_email("   CAPITAL@DOMAIN.ORG ") == "capital@domain.org"
    assert normalize_email("already.clean@domain.com") == "already.clean@domain.com"
    assert normalize_email("") == ""
    assert normalize_email(None) == ""

# 3. Provisioning Idempotency
def test_provisioning_idempotency(client, test_db):
    reset_rate_limiter()
    test_email = "prov.user@testone.com"

    # Clean any prior user
    existing = test_db.query(User).filter(User.email == test_email).first()
    if existing:
        test_db.delete(existing)
        test_db.commit()

    headers = {"x-internal-key": API_KEY}
    payload = {"email": test_email, "name": "Provisioned User"}

    # First call
    resp1 = client.post("/internal/v1/users/provision", json=payload, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()["data"]
    assert data1["email"] == test_email

    # Second call with same email (different case/whitespace)
    resp2 = client.post("/internal/v1/users/provision", json={"email": "  PROV.USER@TESTONE.COM  "}, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert data2["email"] == test_email
    assert data2["user_id"] == data1["user_id"]

    # Verify only 1 record exists in DB
    user_count = test_db.query(User).filter(User.email == test_email).count()
    assert user_count == 1

# 4. Deterministic Portfolio
def test_deterministic_portfolio(test_db):
    orig_seed = settings.SEED_STARTER_PORTFOLIO
    try:
        settings.SEED_STARTER_PORTFOLIO = True
        catalog = load_shared_instruments()
        catalog_map = {item["symbol"]: item for item in catalog}

        email = "portfolio.check@example.com"
        norm_email = normalize_email(email)

        # Test user 1
        u1 = User(
            username="pf_user1",
            email=norm_email,
            full_name="PF User",
            hashed_password="pw",
            client_id="NTPF1",
            masked_pan="TEST-PAN-1111",
            masked_demat="IN300001********",
            mobile="9000011111"
        )
        test_db.add(u1)
        test_db.commit()

        holdings1 = generate_starter_portfolio(test_db, u1)
        test_db.commit()

        # Starting wallet check
        assert u1.available_funds == 1000000.0

        # Capture details
        h1_details = [(h.instrument.symbol, h.quantity, h.average_price) for h in holdings1]

        # Verify Provider A theme: stocks + 1 REIT
        reit_count = sum(1 for h in holdings1 if h.instrument.asset_class == "reit")
        equity_count = sum(1 for h in holdings1 if h.instrument.asset_class == "equity")
        assert reit_count == 1
        assert equity_count >= 3

        # Verify 2-3 overlapping ISINs (RELIANCE, TCS, HDFCBANK)
        overlap_syms = {"RELIANCE", "TCS", "HDFCBANK"}
        overlap_found = [h.instrument.symbol for h in holdings1 if h.instrument.symbol in overlap_syms]
        assert 2 <= len(overlap_found) <= 3

        # Verify prices within +/- 15% of catalog price
        for h in holdings1:
            cat_price = catalog_map[h.instrument.symbol]["price"]
            lower = round(cat_price * 0.85, 2)
            upper = round(cat_price * 1.15, 2)
            assert lower <= h.average_price <= upper

        # Reset holdings and regenerate for the same email
        for h in holdings1:
            test_db.delete(h)
        test_db.commit()

        holdings2 = generate_starter_portfolio(test_db, u1)
        test_db.commit()
        h2_details = [(h.instrument.symbol, h.quantity, h.average_price) for h in holdings2]

        # Must be 100% identical after DB reset / regeneration
        assert h1_details == h2_details
    finally:
        settings.SEED_STARTER_PORTFOLIO = orig_seed

    # Verify existing demo users remain unchanged
    demo1 = test_db.query(User).filter(User.username == "demo1").first()
    assert demo1 is not None
    assert demo1.client_id == "NT0001"
    assert demo1.email == "demo1@niftytrade.local"


# 5. API-key Security & Rate Limiting
def test_api_key_security(client):
    reset_rate_limiter()

    # 1. Missing key = 401
    resp = client.get("/internal/v1/users/demo1@niftytrade.local/profile")
    assert resp.status_code == 401

    # 2. Wrong key = 401
    resp = client.get(
        "/internal/v1/users/demo1@niftytrade.local/profile",
        headers={"x-internal-key": "completely-wrong-key"}
    )
    assert resp.status_code == 401

    # 3. Correct key = 200
    resp = client.get(
        "/internal/v1/users/demo1@niftytrade.local/profile",
        headers={"x-internal-key": API_KEY}
    )
    assert resp.status_code == 200

    # 4. Feature disabled = 404
    original_enabled = settings.INTERNAL_API_ENABLED
    try:
        settings.INTERNAL_API_ENABLED = False
        resp = client.get(
            "/internal/v1/users/demo1@niftytrade.local/profile",
            headers={"x-internal-key": API_KEY}
        )
        assert resp.status_code == 404
    finally:
        settings.INTERNAL_API_ENABLED = original_enabled

    # 5. Rate limit: 60/min
    reset_rate_limiter()
    # Send 60 requests (all 200)
    for _ in range(60):
        r = client.get(
            "/internal/v1/users/demo1@niftytrade.local/profile",
            headers={"x-internal-key": API_KEY}
        )
        assert r.status_code == 200

    # 61st request should be rate-limited (429)
    r61 = client.get(
        "/internal/v1/users/demo1@niftytrade.local/profile",
        headers={"x-internal-key": API_KEY}
    )
    assert r61.status_code == 429
    assert "Rate limit exceeded" in r61.text

# 6. Holdings JSON Parity
def test_holdings_json_parity(client, test_db):
    reset_rate_limiter()
    user = test_db.query(User).filter(User.username == "demo1").first()

    # 1. Get OAuth Bearer token for demo1
    client_id = "aggregator-app"
    client_secret = "demo-secret"
    redirect_uri = "http://localhost:3000/callback"
    code = create_authorization_code(
        db=test_db,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri
    )
    token_resp = client.post(
        "/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri
        }
    )
    token = token_resp.json()["access_token"]

    # 2. Call Public Holdings API
    pub_resp = client.get("/api/v1/holdings", headers={"Authorization": f"Bearer {token}"})
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()

    # 3. Call Internal Holdings API
    internal_resp = client.get(
        f"/internal/v1/users/{user.email}/holdings",
        headers={"x-internal-key": API_KEY}
    )
    assert internal_resp.status_code == 200
    internal_data = internal_resp.json()

    # Verify 100% exact parity in structure and contents
    assert internal_data == pub_data

# 7. Google Account Linking
def test_google_linking(client, test_db):
    reset_rate_limiter()
    email = "googletest@tradeone.org"

    # Pre-provision user via internal API
    headers = {"x-internal-key": API_KEY}
    prov_resp = client.post("/internal/v1/users/provision", json={"email": email}, headers=headers)
    assert prov_resp.status_code == 200

    u = test_db.query(User).filter(User.email == email).first()
    assert u is not None
    assert u.google_id is None
    orig_id = u.id

    # Now login with direct Google Sign-in for the same email
    google_login_resp = client.post(
        "/auth/google/direct",
        data={"email": email, "full_name": "Google Linked Name"},
        follow_redirects=False
    )
    assert google_login_resp.status_code in (302, 303)

    # Confirm user was linked, NOT duplicated
    users_with_email = test_db.query(User).filter(User.email == email).all()
    assert len(users_with_email) == 1
    linked_user = users_with_email[0]
    assert linked_user.id == orig_id
    assert linked_user.google_id == f"g_{email}"

# 8. Outbox Retry & Never Block Trades
def test_outbox_retry(test_db):
    email = "outbox.test@tradeone.org"
    event = enqueue_outbox_event(test_db, email, dispatch_async=False)
    assert event.status == "PENDING"
    assert event.attempts == 0
    assert event.provider == "a"
    assert event.email == email

    # Mock HTTP client to fail 2 times with 500, then succeed on 3rd with 200
    call_count = 0
    def mock_post(url, json, headers):
        nonlocal call_count
        call_count += 1
        # Validate event payload: Send ONLY provider, email, event, occurredAt
        assert set(json.keys()) == {"provider", "email", "event", "occurredAt"}
        assert "quantity" not in json
        assert "holdings" not in json
        if call_count < 3:
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(200, json={"status": "received"})

    mock_client = MagicMock()
    mock_client.post = MagicMock(side_effect=mock_post)

    success = post_event_with_retry(
        event_id=event.id,
        max_attempts=5,
        backoff_base=0.01,
        http_client=mock_client,
        db=test_db
    )

    assert success is True
    assert call_count == 3
    test_db.refresh(event)
    assert event.status == "SENT"
    assert event.attempts == 3

    # Test failure after 10 attempts
    event_fail = enqueue_outbox_event(test_db, "fail@tradeone.org", dispatch_async=False)
    fail_client = MagicMock()
    fail_client.post = MagicMock(return_value=httpx.Response(503, text="Service Unavailable"))

    fail_success = post_event_with_retry(
        event_id=event_fail.id,
        max_attempts=10,
        backoff_base=0.001,
        http_client=fail_client,
        db=test_db
    )


    assert fail_success is False
    test_db.refresh(event_fail)
    assert event_fail.status == "FAILED"
    assert event_fail.attempts == 10
