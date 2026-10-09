import os
import json
import random
import hashlib
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.instrument import Instrument
from app.models.trading import Holding
from app.models.user import User
from app.shared_identity import normalize_email

def load_shared_instruments() -> List[Dict[str, Any]]:
    """Load the shared instruments catalog."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path1 = os.path.join(base_dir, "instruments_shared.json")
    path2 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instruments_shared.json")
    
    for p in (path1, path2):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("instruments_shared.json not found")

def generate_starter_portfolio(db: Session, user: User, force: bool = False) -> List[Holding]:
    """
    Generate a deterministic starter portfolio for a user ONLY if SEED_STARTER_PORTFOLIO is enabled or force is True.
    When SEED_STARTER_PORTFOLIO is false, no holdings are created.
    """
    # 1. Set starting wallet balance
    user.available_funds = getattr(settings, "STARTING_FUNDS", 1000000.0)
    user.used_margin = 0.0

    if not getattr(settings, "SEED_STARTER_PORTFOLIO", False) and not force:
        return []

    norm_email = normalize_email(user.email)

    # 2. Derive deterministic RNG seed from normalized email
    seed_hash = hashlib.sha256(f"starter_portfolio_provider_a:{norm_email}".encode("utf-8")).hexdigest()
    seed_int = int(seed_hash[:16], 16)
    rng = random.Random(seed_int)

    # 3. Load catalog
    catalog = load_shared_instruments()
    catalog_by_symbol = {item["symbol"]: item for item in catalog}

    # Separate stocks and REITs
    all_stocks = [item for item in catalog if item.get("asset_class") == "equity"]
    all_reits = [item for item in catalog if item.get("asset_class") == "reit"]

    # Overlapping candidates (stocks): RELIANCE, TCS, HDFCBANK
    overlap_symbols = ["RELIANCE", "TCS", "HDFCBANK"]
    overlap_count = rng.choice([2, 3])  # 2 or 3 overlapping
    selected_overlap = rng.sample(overlap_symbols, overlap_count)

    # Pick 2 additional stocks from the rest of the equity list
    remaining_stocks = [s["symbol"] for s in all_stocks if s["symbol"] not in overlap_symbols]
    selected_other_stocks = rng.sample(remaining_stocks, 2)

    # Pick exactly 1 REIT
    reit_symbols = [r["symbol"] for r in all_reits]
    selected_reit = rng.choice(reit_symbols)

    selected_symbols = selected_overlap + selected_other_stocks + [selected_reit]

    # 4. Generate holdings with deterministic quantities and avg prices within +/-15%
    created_holdings = []
    for sym in selected_symbols:
        cat_item = catalog_by_symbol[sym]
        base_price = float(cat_item["price"])
        
        # Calculate price within +/- 15% (factor between 0.86 and 1.14)
        pct_delta = rng.uniform(-0.14, 0.14)
        avg_price = round(base_price * (1.0 + pct_delta), 2)
        
        # Deterministic quantity
        qty = rng.choice([10, 15, 20, 25, 30, 40, 50])

        # Find instrument in DB
        db_inst = db.query(Instrument).filter(Instrument.symbol == sym).first()
        if not db_inst:
            # Fallback by isin
            db_inst = db.query(Instrument).filter(Instrument.isin == cat_item["isin"]).first()

        if db_inst:
            holding = Holding(
                user_id=user.id,
                instrument_id=db_inst.id,
                quantity=qty,
                average_price=avg_price
            )
            db.add(holding)
            created_holdings.append(holding)

    db.flush()
    return created_holdings
