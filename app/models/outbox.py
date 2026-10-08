from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.core.database import Base

class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    event = Column(String, nullable=False)
    occurred_at = Column(String, nullable=False)
    status = Column(String, default="PENDING", index=True)  # PENDING, SENT, FAILED
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=10)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
