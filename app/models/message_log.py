from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class MessageLog(SQLModel, table=True):
    """Log of all WhatsApp messages (inbound and outbound)."""

    __tablename__ = "message_log"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    direction: str  # "inbound" or "outbound"
    phone_e164: str = Field(index=True)  # E.164 format: +85212345678
    body: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    media_url: str | None = None  # URL if message contains media
    twilio_sid: str | None = Field(default=None, unique=True, index=True)  # Twilio message SID
    client_id: int | None = Field(default=None, foreign_key="client.id", index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
