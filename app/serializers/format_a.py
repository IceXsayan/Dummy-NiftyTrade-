from typing import Any, Dict
from app.serializers.base import BaseSerializer

class FormatASerializer(BaseSerializer):
    """
    Format A: Kite-Connect style with status: "success", data: ...
    """
    def success(self, data: Any, message: str = "") -> Dict[str, Any]:
        resp = {"status": "success", "data": data}
        if message:
            resp["message"] = message
        return resp

    def error(self, message: str, error_type: str = "general_error", code: int = 400) -> Dict[str, Any]:
        return {
            "status": "error",
            "error_type": error_type,
            "message": message
        }

    def serialize_profile(self, user: Any) -> Dict[str, Any]:
        return {
            "user_id": user.client_id,
            "user_name": user.full_name,
            "email": user.email,
            "mobile": user.mobile,
            "pan": user.masked_pan,
            "demat_id": user.masked_demat,
            "bank_account": user.bank_account_masked,
            "bank_name": user.bank_name
        }

    def serialize_holding(self, h: Any) -> Dict[str, Any]:
        inst = h.instrument
        current_val = round(h.quantity * inst.current_price, 2)
        inv_val = round(h.quantity * h.average_price, 2)
        pnl = round(current_val - inv_val, 2)
        pnl_pct = round((pnl / inv_val) * 100, 2) if inv_val > 0 else 0.0

        return {
            "tradingsymbol": inst.symbol,
            "isin": inst.isin,
            "exchange": inst.exchange,
            "quantity": h.quantity,
            "average_price": round(h.average_price, 2),
            "last_price": round(inst.current_price, 2),
            "close_price": round(inst.previous_close, 2),
            "pnl": pnl,
            "pnl_percentage": pnl_pct,
            "day_change": round(inst.day_change, 2),
            "day_change_percentage": round(inst.day_change_percentage, 2),
            "asset_class": inst.asset_class,
            "sector": inst.sector,
            "invested_value": inv_val,
            "current_value": current_val
        }

    def serialize_position(self, p: Any) -> Dict[str, Any]:
        inst = p.instrument
        return {
            "tradingsymbol": inst.symbol,
            "isin": inst.isin,
            "exchange": inst.exchange,
            "product": p.product_type,
            "quantity": p.quantity,
            "buy_quantity": p.buy_quantity,
            "sell_quantity": p.sell_quantity,
            "buy_price": p.buy_average,
            "sell_price": p.sell_average,
            "last_price": round(inst.current_price, 2),
            "pnl": p.pnl,
            "m2m": p.pnl,
            "day_change_percentage": round(inst.day_change_percentage, 2)
        }

    def serialize_order(self, o: Any) -> Dict[str, Any]:
        return {
            "order_id": o.order_id,
            "tradingsymbol": o.instrument.symbol,
            "isin": o.instrument.isin,
            "exchange": o.instrument.exchange,
            "transaction_type": o.transaction_type,
            "order_type": o.order_type,
            "product": o.product_type,
            "quantity": o.quantity,
            "price": o.price,
            "average_price": o.average_executed_price or 0.0,
            "status": o.status,
            "status_message": o.rejection_reason or "",
            "order_timestamp": o.created_at.isoformat() if o.created_at else None,
            "exchange_timestamp": o.executed_at.isoformat() if o.executed_at else None
        }

    def serialize_trade(self, t: Any) -> Dict[str, Any]:
        return {
            "trade_id": t.trade_id,
            "order_id": t.order.order_id if t.order else None,
            "tradingsymbol": t.instrument.symbol,
            "isin": t.instrument.isin,
            "exchange": t.instrument.exchange,
            "transaction_type": t.transaction_type,
            "product": t.product_type,
            "quantity": t.quantity,
            "average_price": t.price,
            "fill_timestamp": t.trade_time.isoformat() if t.trade_time else None
        }

    def serialize_funds(self, user: Any) -> Dict[str, Any]:
        return {
            "net": round(user.available_funds + user.used_margin, 2),
            "available": {
                "cash": round(user.available_funds, 2),
                "collateral": 0.0,
                "intraday_payin": 0.0
            },
            "utilised": {
                "debits": round(user.used_margin, 2),
                "exposure": 0.0,
                "m2m_unrealised": 0.0
            }
        }

    def serialize_instrument(self, inst: Any) -> Dict[str, Any]:
        return {
            "symbol": inst.symbol,
            "name": inst.name,
            "isin": inst.isin,
            "exchange": inst.exchange,
            "asset_class": inst.asset_class,
            "sector": inst.sector,
            "last_price": round(inst.current_price, 2),
            "day_change": round(inst.day_change, 2),
            "day_change_percentage": round(inst.day_change_percentage, 2)
        }

    def serialize_quote(self, inst: Any) -> Dict[str, Any]:
        return {
            "tradingsymbol": inst.symbol,
            "isin": inst.isin,
            "last_price": round(inst.current_price, 2),
            "ohlc": {
                "open": round(inst.open_price, 2),
                "high": round(inst.high_price, 2),
                "low": round(inst.low_price, 2),
                "close": round(inst.previous_close, 2)
            },
            "net_change": round(inst.day_change, 2),
            "change_percentage": round(inst.day_change_percentage, 2),
            "volume": inst.volume,
            "lower_circuit_limit": round(inst.previous_close * 0.9, 2),
            "upper_circuit_limit": round(inst.previous_close * 1.1, 2)
        }
