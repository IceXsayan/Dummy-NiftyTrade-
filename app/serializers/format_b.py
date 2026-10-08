from typing import Any, Dict
from app.serializers.base import BaseSerializer

class FormatBSerializer(BaseSerializer):
    """
    Format B: Standard REST API payload (flat structure with code, payload, error)
    """
    def success(self, data: Any, message: str = "") -> Dict[str, Any]:
        return {
            "success": True,
            "payload": data,
            "message": message or "OK"
        }

    def error(self, message: str, error_type: str = "general_error", code: int = 400) -> Dict[str, Any]:
        return {
            "success": False,
            "error": {
                "type": error_type,
                "message": message,
                "code": code
            }
        }

    def serialize_profile(self, user: Any) -> Dict[str, Any]:
        return {
            "id": user.client_id,
            "name": user.full_name,
            "email": user.email,
            "phone": user.mobile,
            "pan": user.masked_pan,
            "demat_account": user.masked_demat
        }

    def serialize_holding(self, h: Any) -> Dict[str, Any]:
        inst = h.instrument
        current_val = round(h.quantity * inst.current_price, 2)
        inv_val = round(h.quantity * h.average_price, 2)
        pnl = round(current_val - inv_val, 2)
        pnl_pct = round((pnl / inv_val) * 100, 2) if inv_val > 0 else 0.0

        return {
            "symbol": inst.symbol,
            "isin": inst.isin,
            "units": h.quantity,
            "avg_buy_price": round(h.average_price, 2),
            "market_price": round(inst.current_price, 2),
            "total_invested": inv_val,
            "current_valuation": current_val,
            "unrealized_pnl": pnl,
            "unrealized_return_pct": pnl_pct,
            "category": inst.asset_class
        }

    def serialize_position(self, p: Any) -> Dict[str, Any]:
        inst = p.instrument
        return {
            "symbol": inst.symbol,
            "isin": inst.isin,
            "open_quantity": p.quantity,
            "ltp": round(inst.current_price, 2),
            "net_pnl": p.pnl,
            "type": p.product_type
        }

    def serialize_order(self, o: Any) -> Dict[str, Any]:
        return {
            "id": o.order_id,
            "symbol": o.instrument.symbol,
            "side": o.transaction_type,
            "type": o.order_type,
            "units": o.quantity,
            "placed_price": o.price,
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None
        }

    def serialize_trade(self, t: Any) -> Dict[str, Any]:
        return {
            "id": t.trade_id,
            "symbol": t.instrument.symbol,
            "side": t.transaction_type,
            "units": t.quantity,
            "execution_price": t.price,
            "timestamp": t.trade_time.isoformat() if t.trade_time else None
        }

    def serialize_funds(self, user: Any) -> Dict[str, Any]:
        return {
            "total_balance": round(user.available_funds + user.used_margin, 2),
            "cash_available": round(user.available_funds, 2),
            "margin_blocked": round(user.used_margin, 2)
        }

    def serialize_instrument(self, inst: Any) -> Dict[str, Any]:
        return {
            "symbol": inst.symbol,
            "company_name": inst.name,
            "isin": inst.isin,
            "asset_class": inst.asset_class,
            "sector": inst.sector,
            "price": round(inst.current_price, 2)
        }

    def serialize_quote(self, inst: Any) -> Dict[str, Any]:
        return {
            "symbol": inst.symbol,
            "isin": inst.isin,
            "price": round(inst.current_price, 2),
            "day_high": round(inst.high_price, 2),
            "day_low": round(inst.low_price, 2),
            "prev_close": round(inst.previous_close, 2)
        }
