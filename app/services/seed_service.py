import math
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.instrument import Instrument
from app.models.trading import Holding, Position, Order, Trade, Transaction, Watchlist, WatchlistItem
from app.models.oauth import OAuthApp
from app.models.system import SystemConfig, HistoricalPrice

RAW_INSTRUMENTS = [
    # Stocks (Equities)
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "isin": "INE002A01018", "sector": "Energy", "asset_class": "equity", "price": 2920.50, "pe": 28.5, "mcap": 1980000.0, "h52": 3217.90, "l52": 2220.30},
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd", "isin": "INE467B01029", "sector": "Information Technology", "asset_class": "equity", "price": 4150.00, "pe": 32.1, "mcap": 1500000.0, "h52": 4585.00, "l52": 3311.00},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "isin": "INE040A01034", "sector": "Banking & Finance", "asset_class": "equity", "price": 1680.20, "pe": 19.8, "mcap": 1280000.0, "h52": 1794.00, "l52": 1363.55},
    {"symbol": "INFY", "name": "Infosys Ltd", "isin": "INE009A01021", "sector": "Information Technology", "asset_class": "equity", "price": 1845.30, "pe": 26.4, "mcap": 765000.0, "h52": 1991.45, "l52": 1358.35},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "isin": "INE090A01021", "sector": "Banking & Finance", "asset_class": "equity", "price": 1260.40, "pe": 18.2, "mcap": 885000.0, "h52": 1332.00, "l52": 913.80},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "isin": "INE030A01027", "sector": "FMCG", "asset_class": "equity", "price": 2480.00, "pe": 56.4, "mcap": 582000.0, "h52": 3034.50, "l52": 2172.05},
    {"symbol": "ITC", "name": "ITC Ltd", "isin": "INE154A01025", "sector": "FMCG", "asset_class": "equity", "price": 495.60, "pe": 27.6, "mcap": 618000.0, "h52": 528.55, "l52": 399.30},
    {"symbol": "SBIN", "name": "State Bank of India", "isin": "INE062A01020", "sector": "Banking & Finance", "asset_class": "equity", "price": 815.25, "pe": 11.5, "mcap": 727000.0, "h52": 912.00, "l52": 555.25},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "isin": "INE397D01024", "sector": "Telecommunication", "asset_class": "equity", "price": 1640.80, "pe": 42.1, "mcap": 980000.0, "h52": 1779.00, "l52": 905.00},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd", "isin": "INE237A01028", "sector": "Banking & Finance", "asset_class": "equity", "price": 1790.00, "pe": 21.3, "mcap": 355000.0, "h52": 1908.00, "l52": 1544.15},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "isin": "INE018A01030", "sector": "Capital Goods", "asset_class": "equity", "price": 3620.00, "pe": 34.2, "mcap": 497000.0, "h52": 3948.00, "l52": 2862.00},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "isin": "INE238A01034", "sector": "Banking & Finance", "asset_class": "equity", "price": 1220.50, "pe": 14.5, "mcap": 376000.0, "h52": 1339.65, "l52": 951.40},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Ltd", "isin": "INE021A01026", "sector": "Consumer Durables", "asset_class": "equity", "price": 2980.00, "pe": 52.8, "mcap": 285000.0, "h52": 3422.00, "l52": 2670.10},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "isin": "INE585B01010", "sector": "Automobile", "asset_class": "equity", "price": 12450.00, "pe": 29.4, "mcap": 391000.0, "h52": 13675.00, "l52": 9737.55},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd", "isin": "INE044A01036", "sector": "Healthcare", "asset_class": "equity", "price": 1820.00, "pe": 38.6, "mcap": 436000.0, "h52": 1960.00, "l52": 1098.20},
    {"symbol": "TITAN", "name": "Titan Company Ltd", "isin": "INE280A01028", "sector": "Consumer Goods", "asset_class": "equity", "price": 3480.00, "pe": 78.2, "mcap": 309000.0, "h52": 3868.00, "l52": 3055.00},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "isin": "INE296A01024", "sector": "Banking & Finance", "asset_class": "equity", "price": 7150.00, "pe": 31.5, "mcap": 442000.0, "h52": 7822.00, "l52": 6160.00},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "isin": "INE155A01022", "sector": "Automobile", "asset_class": "equity", "price": 960.50, "pe": 16.8, "mcap": 353000.0, "h52": 1179.05, "l52": 621.50},
    {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "isin": "INE081A01020", "sector": "Metals & Mining", "asset_class": "equity", "price": 155.40, "pe": 15.2, "mcap": 194000.0, "h52": 184.60, "l52": 118.00},
    {"symbol": "NTPC", "name": "NTPC Ltd", "isin": "INE733E01010", "sector": "Power", "asset_class": "equity", "price": 410.20, "pe": 18.4, "mcap": 398000.0, "h52": 448.45, "l52": 230.15},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Ltd", "isin": "INE752E01010", "sector": "Power", "asset_class": "equity", "price": 335.50, "pe": 20.1, "mcap": 312000.0, "h52": 366.25, "l52": 196.30},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Ltd", "isin": "INE101A01026", "sector": "Automobile", "asset_class": "equity", "price": 3050.00, "pe": 30.5, "mcap": 379000.0, "h52": 3225.00, "l52": 1495.00},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "isin": "INE423A01024", "sector": "Metals & Mining", "asset_class": "equity", "price": 3120.00, "pe": 85.0, "mcap": 355000.0, "h52": 3743.00, "l52": 2142.00},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Ltd", "isin": "INE742F01042", "sector": "Infrastructure", "asset_class": "equity", "price": 1420.00, "pe": 35.4, "mcap": 306000.0, "h52": 1607.95, "l52": 775.00},
    {"symbol": "COALINDIA", "name": "Coal India Ltd", "isin": "INE522F01014", "sector": "Energy", "asset_class": "equity", "price": 485.00, "pe": 8.9, "mcap": 298000.0, "h52": 543.55, "l52": 284.10},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd", "isin": "INE860A01027", "sector": "Information Technology", "asset_class": "equity", "price": 1780.00, "pe": 27.2, "mcap": 483000.0, "h52": 1888.00, "l52": 1215.00},
    {"symbol": "WIPRO", "name": "Wipro Ltd", "isin": "INE075A01022", "sector": "Information Technology", "asset_class": "equity", "price": 545.20, "pe": 23.4, "mcap": 285000.0, "h52": 580.00, "l52": 375.00},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation Ltd", "isin": "INE213A01029", "sector": "Energy", "asset_class": "equity", "price": 295.40, "pe": 7.8, "mcap": 371000.0, "h52": 344.75, "l52": 179.80},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Ltd", "isin": "INE918I01026", "sector": "Banking & Finance", "asset_class": "equity", "price": 1850.00, "pe": 34.0, "mcap": 295000.0, "h52": 2029.90, "l52": 1419.05},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "isin": "INE481G01011", "sector": "Materials", "asset_class": "equity", "price": 11200.00, "pe": 44.5, "mcap": 323000.0, "h52": 12130.00, "l52": 8000.00},
    {"symbol": "NESTLEIND", "name": "Nestle India Ltd", "isin": "INE239A01024", "sector": "FMCG", "asset_class": "equity", "price": 2520.00, "pe": 74.2, "mcap": 243000.0, "h52": 2777.00, "l52": 2145.00},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Ltd", "isin": "INE019A01038", "sector": "Metals & Mining", "asset_class": "equity", "price": 985.00, "pe": 24.5, "mcap": 241000.0, "h52": 1060.00, "l52": 737.00},
    {"symbol": "GRASIM", "name": "Grasim Industries Ltd", "isin": "INE047A01021", "sector": "Materials", "asset_class": "equity", "price": 2680.00, "pe": 31.8, "mcap": 182000.0, "h52": 2875.00, "l52": 1860.00},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd", "isin": "INE669C01036", "sector": "Information Technology", "asset_class": "equity", "price": 1580.00, "pe": 41.2, "mcap": 154000.0, "h52": 1715.00, "l52": 1090.00},
    {"symbol": "CIPLA", "name": "Cipla Ltd", "isin": "INE059A01026", "sector": "Healthcare", "asset_class": "equity", "price": 1610.00, "pe": 28.6, "mcap": 130000.0, "h52": 1702.00, "l52": 1131.00},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Ltd", "isin": "INE089A01023", "sector": "Healthcare", "asset_class": "equity", "price": 6650.00, "pe": 22.4, "mcap": 111000.0, "h52": 7104.00, "l52": 5212.00},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Ltd", "isin": "INE437A01024", "sector": "Healthcare", "asset_class": "equity", "price": 6950.00, "pe": 72.1, "mcap": 99000.0, "h52": 7450.00, "l52": 4725.00},
    {"symbol": "TATACONSUM", "name": "Tata Consumer Products Ltd", "isin": "INE192A01025", "sector": "FMCG", "asset_class": "equity", "price": 1180.00, "pe": 65.4, "mcap": 116000.0, "h52": 1269.00, "l52": 850.00},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Ltd", "isin": "INE066A01021", "sector": "Automobile", "asset_class": "equity", "price": 4850.00, "pe": 33.2, "mcap": 133000.0, "h52": 5100.00, "l52": 3375.00},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Ltd", "isin": "INE361B01024", "sector": "Healthcare", "asset_class": "equity", "price": 5200.00, "pe": 68.5, "mcap": 138000.0, "h52": 6125.00, "l52": 3350.00},
    {"symbol": "BRITANNIA", "name": "Britannia Industries Ltd", "isin": "INE216A01030", "sector": "FMCG", "asset_class": "equity", "price": 5950.00, "pe": 58.2, "mcap": 143000.0, "h52": 6472.00, "l52": 4440.00},
    {"symbol": "BEL", "name": "Bharat Electronics Ltd", "isin": "INE263A01024", "sector": "Capital Goods", "asset_class": "equity", "price": 305.00, "pe": 44.0, "mcap": 223000.0, "h52": 340.50, "l52": 127.00},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Ltd", "isin": "INE066F01012", "sector": "Aerospace & Defence", "asset_class": "equity", "price": 4420.00, "pe": 36.5, "mcap": 295000.0, "h52": 5675.00, "l52": 1900.00},

    # REITs (2)
    {"symbol": "EMBASSY", "name": "Embassy Office Parks REIT", "isin": "INE041025011", "sector": "Real Estate", "asset_class": "reit", "price": 385.50, "pe": 24.0, "mcap": 36500.0, "h52": 415.00, "l52": 305.00},
    {"symbol": "MINDSPACE", "name": "Mindspace Business Parks REIT", "isin": "INE0CCU25019", "sector": "Real Estate", "asset_class": "reit", "price": 360.20, "pe": 22.5, "mcap": 21300.0, "h52": 390.00, "l52": 298.00},

    # InvITs (2)
    {"symbol": "INDIGRID", "name": "India Grid Trust InvIT", "isin": "INE219X23014", "sector": "Infrastructure", "asset_class": "invit", "price": 138.40, "pe": 16.0, "mcap": 10800.0, "h52": 148.00, "l52": 125.00},
    {"symbol": "IRBINVIT", "name": "IRB InvIT Fund", "isin": "INE183W23014", "sector": "Infrastructure", "asset_class": "invit", "price": 64.20, "pe": 14.5, "mcap": 3720.0, "h52": 72.50, "l52": 56.00},

    # Bonds & SGBs (3)
    {"symbol": "SGB2031", "name": "Sovereign Gold Bond 2.50% 2031-Series III", "isin": "IN0020210202", "sector": "Government / Gold", "asset_class": "bond", "price": 7450.00, "pe": 0.0, "mcap": 15000.0, "h52": 7800.00, "l52": 5800.00},
    {"symbol": "GOI726_33", "name": "Government of India 7.26% 2033 Bond", "isin": "IN0020230085", "sector": "Government Securities", "asset_class": "bond", "price": 102.50, "pe": 0.0, "mcap": 85000.0, "h52": 104.50, "l52": 98.20},
    {"symbol": "REC820_28", "name": "REC Ltd Tax Free Bond 8.20% 2028", "isin": "INE020B08DF8", "sector": "Corporate Bonds", "asset_class": "bond", "price": 1180.00, "pe": 0.0, "mcap": 12000.0, "h52": 1215.00, "l52": 1140.00}
]

def seed_database(db: Session, force_reset: bool = False):
    """Seed initial data if not already present or if force_reset is True."""
    if force_reset:
        # Clear existing tables in reverse dependency order
        db.query(HistoricalPrice).delete()
        db.query(Trade).delete()
        db.query(Order).delete()
        db.query(Holding).delete()
        db.query(Position).delete()
        db.query(Transaction).delete()
        db.query(WatchlistItem).delete()
        db.query(Watchlist).delete()
        db.query(Instrument).delete()
        db.query(User).delete()
        db.query(OAuthApp).delete()
        db.query(SystemConfig).delete()
        db.commit()

    # Check if already seeded
    existing_inst = db.query(Instrument).first()
    if existing_inst and not force_reset:
        return

    print("Seeding database with fresh NiftyTrade data...")

    # 1. System Config
    system_defaults = {
        "market_open": "true",
        "simulate_outage": "false",
        "slow_mode": "false"
    }
    for k, v in system_defaults.items():
        db.add(SystemConfig(key=k, value=v))
    db.commit()

    # 2. Instruments & 1-year Historical Prices
    instruments_map = {}
    today = datetime.now(timezone.utc).replace(tzinfo=None).date()

    for item in RAW_INSTRUMENTS:
        prev_close = round(item["price"] * random.uniform(0.985, 1.015), 2)
        day_open = round(prev_close * random.uniform(0.995, 1.005), 2)
        high = round(max(day_open, item["price"]) * random.uniform(1.002, 1.015), 2)
        low = round(min(day_open, item["price"]) * random.uniform(0.985, 0.998), 2)
        vol = random.randint(50000, 2500000)

        inst = Instrument(
            symbol=item["symbol"],
            name=item["name"],
            isin=item["isin"],
            exchange="NSE",
            asset_class=item["asset_class"],
            sector=item["sector"],
            current_price=item["price"],
            open_price=day_open,
            high_price=high,
            low_price=low,
            previous_close=prev_close,
            volume=vol,
            pe_ratio=item["pe"],
            market_cap_crores=item["mcap"],
            fifty_two_week_high=item["h52"],
            fifty_two_week_low=item["l52"],
            circuit_limit_pct=10.0
        )
        db.add(inst)
        db.flush()
        instruments_map[item["symbol"]] = inst

        # Generate 1 year of historical daily prices (365 days)
        # Random walk starting from 1 year ago reaching today's price
        history_points = []
        curr_sim_price = item["price"] * random.uniform(0.80, 0.95)
        for d in range(365, 0, -1):
            date_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            # Drift towards target price
            target_diff = (item["price"] - curr_sim_price) / max(d, 1)
            pct_change = random.gauss(0.0005, 0.015)
            curr_sim_price = max(curr_sim_price * (1 + pct_change) + target_diff * 0.1, 5.0)
            
            day_o = round(curr_sim_price * random.uniform(0.995, 1.005), 2)
            day_h = round(day_o * random.uniform(1.002, 1.02), 2)
            day_l = round(day_o * random.uniform(0.98, 0.998), 2)
            day_c = round(random.uniform(day_l, day_h), 2)
            v = random.randint(30000, 1500000)

            history_points.append(
                HistoricalPrice(
                    instrument_id=inst.id,
                    date=date_str,
                    open=day_o,
                    high=day_h,
                    low=day_l,
                    close=day_c,
                    volume=v
                )
            )
        db.bulk_save_objects(history_points)

    db.commit()

    # 3. Clean slate: No demo users or fake portfolios are pre-seeded.
    # Users register or log in with their Google account to start fresh with zero balance.

    # 4. Watchlists are created individually by users upon account creation.

    # 5. Clean slate: No demo trades, holdings, or positions are seeded.
    # Users start completely fresh with zero balance and zero trades.

    # 9. Seeded OAuth App
    oauth_app = OAuthApp(
        name="Portfolio Aggregator",
        client_id="aggregator-app",
        client_secret_hash=hash_password("demo-secret"),
        redirect_uris="http://localhost:3000/callback,http://localhost:8000/oauth/callback,https://example.com/callback",
        description="Verified third-party portfolio analytics and aggregator app"
    )
    db.add(oauth_app)

    db.commit()
    print("Database seeding completed successfully!")
