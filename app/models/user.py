from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True, unique=True)
    name: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(default="customer")  # customer, physio, admin

    conversation_state: str = Field(default="idle")
    last_proposed_start: Optional[datetime] = None
    last_proposed_duration: Optional[int] = None
    active_appointment_id: Optional[int] = None
