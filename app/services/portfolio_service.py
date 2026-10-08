from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.trading import Holding, Position

def get_portfolio_summary(db: Session, user: User) -> Dict[str, Any]:
    holdings = db.query(Holding).filter(Holding.user_id == user.id).all()
    positions = db.query(Position).filter(Position.user_id == user.id).all()

    total_invested = 0.0
    total_current = 0.0
    day_pnl_holdings = 0.0

    sector_map: Dict[str, float] = {}
    asset_class_map: Dict[str, float] = {
        "equity": 0.0,
        "reit": 0.0,
        "invit": 0.0,
        "bond": 0.0
    }

    holding_items = []
    for h in holdings:
        inst = h.instrument
        cur_val = round(h.quantity * inst.current_price, 2)
        inv_val = round(h.quantity * h.average_price, 2)
        day_chg = round(h.quantity * inst.day_change, 2)
        pnl = round(cur_val - inv_val, 2)
        pnl_pct = round((pnl / inv_val) * 100, 2) if inv_val > 0 else 0.0

        total_invested += inv_val
        total_current += cur_val
        day_pnl_holdings += day_chg

        # Sector
        sec = inst.sector or "Other"
        sector_map[sec] = sector_map.get(sec, 0.0) + cur_val

        # Asset class
        ac = (inst.asset_class or "equity").lower()
        asset_class_map[ac] = asset_class_map.get(ac, 0.0) + cur_val

        holding_items.append({
            "id": h.id,
            "symbol": inst.symbol,
            "name": inst.name,
            "isin": inst.isin,
            "sector": inst.sector,
            "asset_class": inst.asset_class,
            "quantity": h.quantity,
            "average_price": h.average_price,
            "current_price": inst.current_price,
            "invested_value": inv_val,
            "current_value": cur_val,
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "day_change": day_chg,
            "day_change_pct": inst.day_change_percentage
        })

    # Intraday PnL
    positions_pnl = sum(p.pnl for p in positions)
    
    total_pnl = round((total_current - total_invested) + positions_pnl, 2)
    total_pnl_percentage = round((total_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0
    total_day_pnl = round(day_pnl_holdings + positions_pnl, 2)
    net_worth = round(user.available_funds + total_current + user.used_margin, 2)

    # Sort holdings for top holdings
    top_holdings = sorted(holding_items, key=lambda x: x["current_value"], reverse=True)[:5]

    # Normalize sectors and asset classes to percentages
    sector_alloc = []
    if total_current > 0:
        for s_name, s_val in sorted(sector_map.items(), key=lambda x: x[1], reverse=True):
            sector_alloc.append({
                "label": s_name,
                "value": round(s_val, 2),
                "percentage": round((s_val / total_current) * 100, 1)
            })

    asset_alloc = []
    if total_current > 0:
        for ac_name, ac_val in asset_class_map.items():
            if ac_val > 0:
                asset_alloc.append({
                    "label": ac_name.upper(),
                    "value": round(ac_val, 2),
                    "percentage": round((ac_val / total_current) * 100, 1)
                })

    return {
        "net_worth": net_worth,
        "available_funds": round(user.available_funds, 2),
        "used_margin": round(user.used_margin, 2),
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_pnl": total_pnl,
        "total_pnl_percentage": total_pnl_percentage,
        "day_pnl": total_day_pnl,
        "holdings": holding_items,
        "top_holdings": top_holdings,
        "sector_allocation": sector_alloc,
        "asset_allocation": asset_alloc
    }
