from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Payment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    amount: float
    status: str = Field(default="pending")  # pending, approved, rejected
    payment_method: str  # credit_card, fps
    proof_url: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
