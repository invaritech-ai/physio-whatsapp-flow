from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True, unique=True)
    name: str | None = None
    email: str | None = None
    role: str = Field(default="customer")  # customer, physio, admin

    conversation_state: str = Field(default="idle")
    last_proposed_start: datetime | None = None
    last_proposed_duration: int | None = None
    active_appointment_id: int | None = None
