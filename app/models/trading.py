from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base

class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, default=0, nullable=False)
    average_price = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="holdings")
    instrument = relationship("Instrument", back_populates="holdings")

    @property
    def invested_value(self) -> float:
        return round(self.quantity * self.average_price, 2)

    @property
    def current_value(self) -> float:
        return round(self.quantity * self.instrument.current_price, 2)

    @property
    def pnl(self) -> float:
        return round(self.current_value - self.invested_value, 2)

    @property
    def pnl_percentage(self) -> float:
        if self.invested_value == 0:
            return 0.0
        return round((self.pnl / self.invested_value) * 100, 2)

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True)
    product_type = Column(String, default="MIS")  # MIS (Intraday)
    quantity = Column(Integer, default=0)         # Net open quantity (+ for long, - for short)
    buy_quantity = Column(Integer, default=0)
    sell_quantity = Column(Integer, default=0)
    buy_value = Column(Float, default=0.0)
    sell_value = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="positions")
    instrument = relationship("Instrument", back_populates="positions")

    @property
    def buy_average(self) -> float:
        return round(self.buy_value / self.buy_quantity, 2) if self.buy_quantity > 0 else 0.0

    @property
    def sell_average(self) -> float:
        return round(self.sell_value / self.sell_quantity, 2) if self.sell_quantity > 0 else 0.0

    @property
    def pnl(self) -> float:
        # Realized + Unrealized
        # Realized: (sell_avg - buy_avg) * min(buy_qty, sell_qty)
        # Unrealized: (current_price - buy_avg) * net_qty (if long) or (sell_avg - current_price) * abs(net_qty) (if short)
        realized = 0.0
        closed_qty = min(self.buy_quantity, self.sell_quantity)
        if closed_qty > 0 and self.buy_quantity > 0 and self.sell_quantity > 0:
            realized = (self.sell_average - self.buy_average) * closed_qty
        
        unrealized = 0.0
        if self.quantity > 0 and self.buy_quantity > 0:
            unrealized = (self.instrument.current_price - self.buy_average) * self.quantity
        elif self.quantity < 0 and self.sell_quantity > 0:
            unrealized = (self.sell_average - self.instrument.current_price) * abs(self.quantity)
        return round(realized + unrealized, 2)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_type = Column(String, nullable=False)  # BUY, SELL
    order_type = Column(String, nullable=False)        # MARKET, LIMIT
    product_type = Column(String, default="CNC")       # CNC (Delivery), MIS (Intraday)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)              # Limit price or placed market price
    average_executed_price = Column(Float, nullable=True)
    status = Column(String, default="OPEN", index=True) # OPEN, EXECUTED, CANCELLED, REJECTED
    rejection_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="orders")
    instrument = relationship("Instrument", back_populates="orders")
    trades = relationship("Trade", back_populates="order")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(String, unique=True, index=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_type = Column(String, nullable=False)  # BUY, SELL
    product_type = Column(String, nullable=False)      # CNC, MIS
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    trade_time = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="trades")
    instrument = relationship("Instrument", back_populates="trades")
    order = relationship("Order", back_populates="trades")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String, nullable=False)  # DEPOSIT, WITHDRAWAL, TRADE_DEBIT, TRADE_CREDIT
    amount = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    reference_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")

class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)

    user = relationship("User", back_populates="watchlists")
    items = relationship("WatchlistItem", back_populates="watchlist", cascade="all, delete-orphan")

class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True)

    watchlist = relationship("Watchlist", back_populates="items")
    instrument = relationship("Instrument", back_populates="watchlist_items")
