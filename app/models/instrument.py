from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import relationship

from app.core.database import Base

class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    isin = Column(String, unique=True, index=True, nullable=False)
    exchange = Column(String, default="NSE")
    asset_class = Column(String, default="equity")  # equity, reit, invit, bond
    sector = Column(String, default="Diversified")
    
    current_price = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    previous_close = Column(Float, nullable=False)
    volume = Column(Integer, default=100000)
    
    pe_ratio = Column(Float, default=25.0)
    market_cap_crores = Column(Float, default=50000.0)
    fifty_two_week_high = Column(Float, nullable=False)
    fifty_two_week_low = Column(Float, nullable=False)
    circuit_limit_pct = Column(Float, default=10.0)

    # Relationships
    holdings = relationship("Holding", back_populates="instrument")
    positions = relationship("Position", back_populates="instrument")
    orders = relationship("Order", back_populates="instrument")
    trades = relationship("Trade", back_populates="instrument")
    historical_prices = relationship("HistoricalPrice", back_populates="instrument", cascade="all, delete-orphan")
    watchlist_items = relationship("WatchlistItem", back_populates="instrument", cascade="all, delete-orphan")

    @property
    def day_change(self) -> float:
        return round(self.current_price - self.previous_close, 2)

    @property
    def day_change_percentage(self) -> float:
        if not self.previous_close or self.previous_close == 0:
            return 0.0
        return round(((self.current_price - self.previous_close) / self.previous_close) * 100, 2)
