from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./physio.db"

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_number: str = "whatsapp:+14155238886"

    calendly_api_token: str | None = None

    # Webhook security
    twilio_webhook_secret: str | None = None
    calendly_webhook_secret: str | None = None

    # Currency
    default_currency: str = "HKD"

    neon_auth_url: str | None = None
    neon_jwks_url: str | None = None
    neon_jwt_issuer: str | None = None
    neon_jwt_audience: str | None = None

    debug_mode: bool = False
    public_base_url: str | None = None

    # Celery + Redis
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"


settings = Settings()
