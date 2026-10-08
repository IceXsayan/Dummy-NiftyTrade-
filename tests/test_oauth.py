from datetime import datetime, timedelta, timezone
from app.models.user import User
from app.models.oauth import OAuthToken
from app.services.oauth_service import create_authorization_code

def test_oauth_flow_and_api_access(client, test_db):
    user = test_db.query(User).filter(User.username == "demo1").first()
    client_id = "aggregator-app"
    client_secret = "demo-secret"
    redirect_uri = "http://localhost:3000/callback"

    # 1. Generate auth code
    code = create_authorization_code(
        db=test_db,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri
    )
    assert code.startswith("nac_")

    # 2. Exchange code for access token via POST /oauth/token
    token_resp = client.post(
        "/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri
        }
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "Bearer"
    assert token_data["user_id"] == "NT0001"
    
    access_token = token_data["access_token"]

    # 3. Call GET /api/v1/profile with Bearer token
    profile_resp = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert profile_resp.status_code == 200
    p_json = profile_resp.json()
    assert p_json["status"] == "success"
    assert p_json["data"]["user_id"] == "NT0001"
    assert p_json["data"]["email"] == "demo1@niftytrade.local"

    # 4. Call GET /api/v1/holdings
    holdings_resp = client.get(
        "/api/v1/holdings",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert holdings_resp.status_code == 200
    h_json = holdings_resp.json()
    assert h_json["status"] == "success"
    assert isinstance(h_json["data"], list)
    assert len(h_json["data"]) > 0
    # Check fields in first holding
    first_h = h_json["data"][0]
    assert "tradingsymbol" in first_h
    assert "isin" in first_h
    assert "quantity" in first_h
    assert "average_price" in first_h
    assert "last_price" in first_h

    # 5. Test expired token behavior
    # Manually expire the token in DB
    tok_obj = test_db.query(OAuthToken).filter(OAuthToken.user_id == user.id).order_by(OAuthToken.created_at.desc()).first()
    tok_obj.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    test_db.commit()

    expired_resp = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert expired_resp.status_code == 401
    exp_json = expired_resp.json()
    assert exp_json.get("detail", {}).get("error") == "token_expired" or exp_json.get("error") == "token_expired"

def test_oauth_token_revocation(client, test_db):
    user = test_db.query(User).filter(User.username == "demo2").first()
    code = create_authorization_code(
        db=test_db,
        client_id="aggregator-app",
        user_id=user.id,
        redirect_uri="http://localhost:3000/callback"
    )

    token_resp = client.post(
        "/oauth/token",
        data={
            "client_id": "aggregator-app",
            "client_secret": "demo-secret",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback"
        }
    )
    access_token = token_resp.json()["access_token"]

    # Revoke token
    revoke_resp = client.post("/oauth/revoke", data={"token": access_token})
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    # Call API with revoked token
    denied_resp = client.get(
        "/api/v1/profile",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert denied_resp.status_code == 401
