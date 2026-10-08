from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    BROKER_NAME: str = "NiftyTrade"
    SECRET_KEY: str = "niftytrade-super-secret-key-change-in-prod-2026"
    TOKEN_EXPIRY_MINUTES: int = 1440
    RESPONSE_FORMAT: str = "A"
    ADMIN_PASSWORD: str = "admin123"
    CORS_ORIGINS: str = "*"
    DATABASE_URL: str = "sqlite:///./niftytrade.db"
    
    # TradeOne Integration
    PROVIDER_CODE: str = "a"
    DP_NAME: str = "NiftyTrade Securities"
    DP_ID: str = "IN300001"
    SHARED_IDENTITY_SALT: str = "tradeone-shared-identity-salt"
    INTERNAL_API_ENABLED: bool = True
    INTERNAL_API_KEY: str = "tradeone-internal-secret-key"
    TRADEONE_URL: str = "http://localhost:8080"
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    @property
    def cors_origin_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()

