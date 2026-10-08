# NiftyTrade 📈
### Simulated Indian Discount Broker & Kite-Connect-Compatible Sandbox API

NiftyTrade is a full-featured simulated stock broker web application modeled after modern Indian discount brokers (such as Zerodha Kite and Groww). It serves as a sandbox data provider and testing platform for portfolio aggregators, algo-trading bots, and fintech applications.

> **Disclaimer:** All data, market feeds, bank accounts, and trades are strictly simulated. A mandatory disclaimer banner is permanently visible across the platform.

---

## 🌟 Key Highlights

- **Broker Trading Terminal:** Server-rendered HTML with Jinja2 templates, vanilla JavaScript, Chart.js, and sleek Light/Dark mode.
- **50 Real NSE Instruments:** 43 Equities (RELIANCE, TCS, HDFCBANK, INFY, ITC, SBIN, etc.), 2 REITs (EMBASSY, MINDSPACE), 2 InvITs (INDIGRID, IRBINVIT), and 3 Bonds/SGBs (SGB2031, GOI726_33, REC820_28) with real ISINs and 1-year historical OHLCV data.
- **Background Price Simulator:** Asynchronous price simulator generating a realistic random walk every 5 seconds, respecting circuit limits (&plusmn;10%), updating high/low/volume, moving indices (NIFTY 50, SENSEX, BANK NIFTY), and broadcasting ticks over Server-Sent Events (SSE).
- **Auto-Executing Limit Orders:** Open limit orders automatically match and execute when the simulated market price crosses the trigger/limit price.
- **Kite-Connect-Style OAuth 2.0 API:** Full authorization code grant flow (`/oauth/authorize`, `/oauth/token`, `/oauth/revoke`) and Bearer token protected data APIs (`/api/v1/*`).
- **Pluggable Serialization:** Swappable response formats controlled by the `RESPONSE_FORMAT` environment variable (Format A: Kite-Connect style, Format B: Generic REST).
- **Chaos Testing & Admin Controls:** Admin dashboard (`/admin`) to simulate instant trades, expire tokens on-demand (demoing 401 reconnect flows), toggle market hours, simulate outages (503), add artificial latency (slow mode), and edit holdings directly.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+ (tested and compatible through Python 3.14)
- Git

### 2. Installation
```bash
git clone https://github.com/example/nifty-trade.git
cd "NIFTY TRADE"

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Application
Run with one single command:
```bash
python run.py
# Or directly via uvicorn (restricting reload to 'app' directory so SQLite writes don't trigger server restarts):
uvicorn app.main:app --reload --reload-dir app
```

The application will start at: **`http://localhost:8000`**
Swagger API Documentation is available at: **`http://localhost:8000/docs`**

---

## 🔐 Demo Credentials

| Role | Username / Client ID | Password | Profile Highlights |
| :--- | :--- | :--- | :--- |
| **Demo User 1** | `demo1` / `NT0001` | `demo123` | Equity-heavy portfolio (~85-90%), 12 holdings, bluechips + REIT |
| **Demo User 2** | `demo2` / `NT0002` | `demo123` | Fixed-income & yield-heavy profile, Sovereign Gold Bonds, InvITs |
| **Broker Admin** | - | `admin123` | Master access to simulation and chaos toggles at `/admin` |

*(Note: One-click "⚡ Demo 1" and "⚡ Demo 2" buttons are provided directly on the Login page for instant access.)*

---

## ⚙️ Environment Variables

Configure via a `.env` file or environment variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `BROKER_NAME` | `NiftyTrade` | Name displayed across the portal and footers |
| `PROVIDER_CODE` | `a` | TradeOne provider code identifier |
| `DP_NAME` | `NiftyTrade Securities` | Depository Participant Name |
| `DP_ID` | `IN300001` | Depository Participant ID |
| `SECRET_KEY` | `niftytrade-super-secret-key-change-in-prod-2026` | Key used for signing session cookies and HMAC |
| `TOKEN_EXPIRY_MINUTES` | `1440` | Duration before OAuth access tokens expire (in minutes) |
| `RESPONSE_FORMAT` | `A` | Format for API responses (`A` for Kite-style, `B` for REST) |
| `ADMIN_PASSWORD` | `admin123` | Master password for the `/admin` sandbox panel |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated or `*`) |
| `DATABASE_URL` | `sqlite:///./niftytrade.db` | SQLAlchemy database connection string |
| `INTERNAL_API_ENABLED` | `true` | Toggle for `/internal/v1/*` internal endpoints |
| `INTERNAL_API_KEY` | `tradeone-internal-secret-key` | Secret key for `x-internal-key` header authentication |
| `SHARED_IDENTITY_SALT` | `tradeone-shared-identity-salt` | Salt for deterministic identity HMAC across all 4 broker instances |
| `TRADEONE_URL` | `http://localhost:8080` | Base URL of the TradeOne core aggregator service for outbox webhooks |

---


## 🔑 OAuth 2.0 Integration Flow (For Aggregators)

A third-party portfolio aggregator app is pre-registered in the seed database:
- **Client ID:** `aggregator-app`
- **Client Secret:** `demo-secret`
- **Allowed Redirect URIs:** `http://localhost:3000/callback`, `http://localhost:8000/oauth/callback`, `https://example.com/callback`

### Step 1: User Consent & Authorization
Direct the user's browser to:
```
GET http://localhost:8000/oauth/authorize?client_id=aggregator-app&redirect_uri=http://localhost:3000/callback&state=xyz123
```
If the user is logged in and clicks **"Allow & Authorize"**, the browser is redirected to:
```
http://localhost:3000/callback?code=nac_xxxxxxxxxxxx&state=xyz123
```

### Step 2: Exchange Authorization Code for Access Token
Make a server-to-server POST request:
```bash
curl -X POST http://localhost:8000/oauth/token \
  -F "client_id=aggregator-app" \
  -F "client_secret=demo-secret" \
  -F "code=nac_xxxxxxxxxxxx" \
  -F "redirect_uri=http://localhost:3000/callback"
```

**Response (HTTP 200):**
```json
{
  "access_token": "nt_aB3dE...89",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user_id": "NT0001",
  "scope": "read"
}
```

### Step 3: Access Protected Data APIs
Include the token in the `Authorization: Bearer <access_token>` header.

If the token has expired or was revoked via Admin, the API returns **HTTP 401**:
```json
{
  "detail": {
    "error": "token_expired",
    "message": "The access token has expired. Please re-authenticate."
  }
}
```

---

## 📡 Public API Reference & Sample cURL Commands

### 1. User Profile
```bash
curl -X GET http://localhost:8000/api/v1/profile \
  -H "Authorization: Bearer <access_token>"
```

### 2. Delivery Holdings
```bash
curl -X GET http://localhost:8000/api/v1/holdings \
  -H "Authorization: Bearer <access_token>"
```

**Response Format A (`RESPONSE_FORMAT=A`):**
```json
{
  "status": "success",
  "data": [
    {
      "tradingsymbol": "RELIANCE",
      "isin": "INE002A01018",
      "exchange": "NSE",
      "quantity": 25,
      "average_price": 2750.0,
      "last_price": 2920.5,
      "close_price": 2905.0,
      "pnl": 4262.5,
      "pnl_percentage": 6.2,
      "day_change": 15.5,
      "day_change_percentage": 0.53,
      "asset_class": "equity",
      "sector": "Energy",
      "invested_value": 68750.0,
      "current_value": 73012.5
    }
  ]
}
```

### 3. Intraday Positions
```bash
curl -X GET http://localhost:8000/api/v1/positions \
  -H "Authorization: Bearer <access_token>"
```

### 4. Order Book
```bash
curl -X GET http://localhost:8000/api/v1/orders \
  -H "Authorization: Bearer <access_token>"
```

### 5. Executed Trades
```bash
curl -X GET http://localhost:8000/api/v1/trades \
  -H "Authorization: Bearer <access_token>"
```

### 6. Funds & Margin
```bash
curl -X GET http://localhost:8000/api/v1/funds \
  -H "Authorization: Bearer <access_token>"
```

### 7. Quote by ISIN or Symbol
```bash
# By ISIN:
curl -X GET "http://localhost:8000/api/v1/quote?isin=INE002A01018" \
  -H "Authorization: Bearer <access_token>"

# By Symbol:
curl -X GET "http://localhost:8000/api/v1/quote?symbol=TCS" \
  -H "Authorization: Bearer <access_token>"
```

### 8. Batch Quotes
```bash
curl -X GET "http://localhost:8000/api/v1/quotes?isins=INE002A01018,INE467B01029,IN0020210202" \
  -H "Authorization: Bearer <access_token>"
```

### 9. Instrument Master
```bash
curl -X GET http://localhost:8000/api/v1/instruments \
  -H "Authorization: Bearer <access_token>"
```

### 10. Live Market Stream (SSE)
```bash
curl -N http://localhost:8000/api/live-quotes
```

---

## ⚡ TradeOne Internal Broker Integration (`/internal/v1/*`)

NiftyTrade acts as Provider **`a`** within the unified TradeOne ecosystem. Internal endpoints are enabled when `INTERNAL_API_ENABLED=true`.

### Security & Rate Limiting
- **Authentication Header:** `x-internal-key: <INTERNAL_API_KEY>` (e.g. `tradeone-internal-secret-key`)
- **Validation:** Evaluated via constant-time comparison (`secrets.compare_digest`) to prevent timing attacks. Missing or incorrect keys return **HTTP 401 Unauthorized**. The key is never logged.
- **Rate Limit:** Fixed at **60 requests per minute** per client IP. Exceeding requests receive **HTTP 429 Too Many Requests**.
- **Disabled State:** When `INTERNAL_API_ENABLED=false`, all `/internal/v1/*` routes return **HTTP 404 Not Found**.

---

### Endpoints

#### 1. Provision User
```bash
curl -X POST http://localhost:8000/internal/v1/users/provision \
  -H "x-internal-key: tradeone-internal-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"email": "investor@tradeone.org", "name": "Jane Trader"}'
```
- **Idempotency:** If the user already exists, returns the existing profile without duplicating records.
- **Deterministic Identity:** Derives client ID, masked fake PAN, masked fake Aadhaar, mobile, and bank details deterministically from `SHARED_IDENTITY_SALT` and the normalized email. Never generates real-looking PAN/Aadhaar formats.
- **Starter Portfolio:** Creates a deterministic portfolio (Provider A theme: 4-5 stocks + 1 REIT, including 2-3 overlapping ISINs like RELIANCE, TCS, HDFCBANK). Average prices are within &plusmn;15% of current price.
- **Starting Wallet:** ₹10,00,000 cash balance (`available_funds = 1000000.0`).

#### 2. Get User Profile
```bash
curl -X GET http://localhost:8000/internal/v1/users/investor@tradeone.org/profile \
  -H "x-internal-key: tradeone-internal-secret-key"
```

#### 3. Get User Holdings
```bash
curl -X GET http://localhost:8000/internal/v1/users/investor@tradeone.org/holdings \
  -H "x-internal-key: tradeone-internal-secret-key"
```
- **Public Parity:** Returns the **exact same** JSON structure, field names, number formats, and status wrapper as the public `/api/v1/holdings` endpoint.

#### 4. Get User Portfolio Summary
```bash
curl -X GET http://localhost:8000/internal/v1/users/investor@tradeone.org/summary \
  -H "x-internal-key: tradeone-internal-secret-key"
```
Returns available funds, used margin, net worth, total invested, current valuation, total PnL, day PnL, holdings count, and provider code (`a`).

---

### Outbox Pattern & Webhook Events
Whenever holdings are modified (via executed CNC orders, simulated trades, admin modifications, or starter portfolio generation) and committed to the database:
1. An event is enqueued into the `outbox_events` table.
2. An asynchronous background process POSTs the notification to `{TRADEONE_URL}/internal/v1/events`.
3. **Payload:**
   ```json
   {
     "provider": "a",
     "email": "investor@tradeone.org",
     "event": "HOLDINGS_CHANGED",
     "occurredAt": "2026-10-09T01:30:00Z"
   }
   ```
   *Note: Only `provider`, `email`, `event`, and `occurredAt` are transmitted. Holdings quantities are never included in the event.*
4. **Retry & Non-blocking:** Dispatched in a background thread to ensure trades and order executions are never blocked. If delivery fails, it retries with exponential backoff up to 10 attempts.

---

## 🛠️ Admin / Demo Controls (`/admin`)

The `/admin` portal (password: `admin123`) includes interactive tools designed specifically for live demonstrations and sync testing:

1. **Simulate Immediate Trade:** Select a user, stock, BUY/SELL, quantity, and price. Instantly updates the user's holdings and records an executed trade so external aggregators can observe a live diff on their next sync cycle.
2. **Expire Token Instantly:** Forces an issued OAuth token to expire immediately, triggering HTTP 401 `{"error": "token_expired"}` to test reconnection flows in client applications.
3. **Market Hours Toggle:** Instantly switches market state between `OPEN` and `CLOSED`. When closed, prices freeze and market orders are queued as After Market Orders (AMO).
4. **Trigger 60s Outage (503):** Causes all `/api/v1/*` endpoints to return HTTP 503 Service Unavailable for 60 seconds to test client resilience and retry mechanisms.
5. **Slow Mode Toggle:** Injects an artificial 5-second delay into API calls to test loading states and timeouts.
6. **Reset Entire Database:** One-click reset returning all users, holdings, orders, and market prices back to clean seed data.
7. **Direct Holdings Editor:** Add, modify, or delete any user's stock holdings in real time.

---

## 🧪 Running Automated Tests

Run the full test suite using `pytest`:
```bash
pytest -v
```

Tests cover:
- Market and limit order execution
- Funds and margin validation (including 20% MIS margin blocks)
- Insufficient funds / holdings rejection
- Order cancellation and fund refunds
- OAuth 2.0 authorization, code exchange, and token verification
- Token expiration (401 `token_expired`) and revocation

---

## 🐳 Docker & Cloud Deployment (Render / Railway / Fly.io)

### Build and Run with Docker Locally
```bash
docker build -t niftytrade:latest .
docker run -p 8000:8000 niftytrade:latest
```

### Deploy to Render
1. Create a new **Web Service** on Render and link your GitHub repository.
2. Select **Docker** environment or **Python** environment:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Configure environment variables in the Render dashboard:
   - `BROKER_NAME`: `NiftyTrade`
   - `ADMIN_PASSWORD`: `<your-secure-password>`
   - `SECRET_KEY`: `<your-random-secret>`
   - `RESPONSE_FORMAT`: `A`
4. The service will be live with full health check support at `/health`.
