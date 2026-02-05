from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./physio.db"

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_number: str = "whatsapp:+14155238886"

    calendly_api_token: str | None = None

    admin_phone_number: str | None = None
    physio_phone_number: str | None = None

    neon_auth_url: str | None = None
    neon_jwks_url: str | None = None
    neon_jwt_issuer: str | None = None
    neon_jwt_audience: str | None = None

    debug_mode: bool = False
    public_base_url: str | None = None


settings = Settings()
