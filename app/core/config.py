from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./physio.db"

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_number: str = "whatsapp:+14155238886"
    # Optional WhatsApp Content Template SID (HX...) for invoice receipts.
    # When set, receipt sends use template mode and work outside the 24h window.
    twilio_whatsapp_receipt_content_sid: str | None = None
    # Optional template variable index for dynamic media URL (e.g. 3 for {{3}}).
    # Leave unset when template media URL is fixed in Twilio Content Builder.
    twilio_whatsapp_receipt_media_var_index: int | None = None
    # Content SID for the session-booking confirmation template (physio_session_booked).
    # When set, booking confirmations use this template and work outside the 24h window.
    twilio_whatsapp_session_booked_content_sid: str | None = None

    calendly_api_token: str | None = None

    # Encryption key for sensitive data (Fernet key - must be 32 url-safe base64-encoded bytes)
    encryption_key: str | None = None

    # Webhook security
    twilio_webhook_secret: str | None = None
    calendly_webhook_secret: str | None = None

    # Currency
    default_currency: str = "HKD"

    # Invoice document storage (temp staging dir for PDF rendering before S3 upload)
    invoice_storage_dir: str = "/tmp/physio_invoice_pdfs"

    # S3-compatible invoice object storage (AWS S3 / OCI Object Storage compat endpoint)
    invoice_s3_bucket: str | None = None
    invoice_s3_region: str | None = None
    invoice_s3_endpoint_url: str | None = None
    invoice_s3_prefix: str = "invoices"
    invoice_s3_access_key_id: str | None = None
    invoice_s3_secret_access_key: str | None = None
    invoice_s3_public_base_url: str | None = None
    invoice_s3_presign_ttl_seconds: int = 3600  # TTL for on-demand pre-signed download URLs

    # Invoice renderer
    invoice_renderer: str = "basic"  # basic|latex
    invoice_latex_template_path: str = "templates/invoices/receipt.tex"
    invoice_latex_engine: str = "pdflatex"
    invoice_latex_timeout_seconds: int = 30
    invoice_latex_fallback_to_basic: bool = True

    invoice_timezone: str = "Asia/Hong_Kong"
    business_name: str = "Movement Group Limited"
    business_address: str = "19A-19B High Street, G/F High House, Hong Kong, Sai Ying Pun, NA"
    business_phone: str = "63121852"
    business_email: str = "hello@movementfitnesshk.com"

    # Reschedule/cancel via WhatsApp is blocked within this many hours of the
    # appointment; clients are directed to the admin WhatsApp number instead.
    reschedule_min_hours_advance: int = 24
    admin_whatsapp_number: str | None = None

    neon_auth_url: str | None = None
    neon_jwks_url: str | None = None
    neon_jwt_issuer: str | None = None
    neon_jwt_audience: str | None = None
    auth_enforce_access_ttl: bool = False
    auth_max_access_token_ttl_seconds: int = 600

    app_env: str = "development"
    debug_mode: bool = False
    # When true, outbound WhatsApp uses print-only (no Twilio API). Independent of DEBUG_MODE
    # so verbose tracing does not silently drop patient messages.
    twilio_dry_run: bool = False
    public_base_url: str | None = None
    web_base_url: str | None = None

    # Periodic sync intervals
    sync_interval_minutes: int | None = None
    sync_interval_hours: int = 4
    availability_sync_interval_minutes: int = 30
    availability_cache_ttl_minutes: int = 45

    # Booking follow-up nudges
    booking_followup_enabled: bool = False
    booking_followup_first_delay_seconds: int = 3600
    booking_followup_second_delay_seconds: int = 21600

    @property
    def sync_interval_seconds(self) -> int:
        if self.sync_interval_minutes is not None:
            return self.sync_interval_minutes * 60
        return self.sync_interval_hours * 60 * 60

    @property
    def availability_sync_interval_seconds(self) -> int:
        return self.availability_sync_interval_minutes * 60

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        env = self.app_env.strip().lower()
        if env in {"production", "prod"} and not (self.web_base_url and self.web_base_url.strip()):
            raise ValueError("WEB_BASE_URL must be configured when APP_ENV is production/prod.")
        if self.sync_interval_hours < 1:
            raise ValueError("SYNC_INTERVAL_HOURS must be >= 1.")
        if self.sync_interval_minutes is not None and self.sync_interval_minutes < 1:
            raise ValueError("SYNC_INTERVAL_MINUTES must be >= 1 when set.")
        if self.availability_sync_interval_minutes < 1:
            raise ValueError("AVAILABILITY_SYNC_INTERVAL_MINUTES must be >= 1.")
        if self.availability_cache_ttl_minutes < 1:
            raise ValueError("AVAILABILITY_CACHE_TTL_MINUTES must be >= 1.")
        return self


settings = Settings()
