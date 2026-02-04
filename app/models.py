from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True, unique=True)
    name: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(default="customer")  # customer, physio, admin

    conversation_state: str = Field(default="idle")
    last_proposed_start: Optional[datetime] = None
    last_proposed_duration: Optional[int] = None
    active_appointment_id: Optional[int] = None


class Appointment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id")
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str = Field(default="scheduled")  # scheduled, started, completed, cancelled
    calendly_uuid: str
    reminder_sent: bool = Field(default=False)
    physio_notified: bool = Field(default=False)

    physio_payment_status: Optional[str] = None
    physio_payment_method: Optional[str] = None


class Payment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    amount: float
    status: str = Field(default="pending")  # pending, approved, rejected
    payment_method: str  # credit_card, fps
    proof_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SessionNote(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    note_text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="physio")
