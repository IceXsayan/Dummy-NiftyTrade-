from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime

from app.core.database import Base

class OAuthApp(Base):
    __tablename__ = "oauth_apps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    client_id = Column(String, unique=True, index=True, nullable=False)
    client_secret_hash = Column(String, nullable=False)
    redirect_uris = Column(String, nullable=False)  # Comma-separated list of allowed URIs
    description = Column(String, default="Third-party portfolio aggregator application")
    created_at = Column(DateTime, default=datetime.utcnow)

class OAuthAuthCode(Base):
    __tablename__ = "oauth_auth_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    client_id = Column(String, nullable=False)
    user_id = Column(Integer, nullable=False)
    redirect_uri = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    token_preview = Column(String, nullable=False)  # First 8 chars for user profile display
    client_id = Column(String, nullable=False)
    user_id = Column(Integer, nullable=False, index=True)
    scope = Column(String, default="read")
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
