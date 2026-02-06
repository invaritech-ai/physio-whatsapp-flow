from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Appointment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id")
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str = Field(default="scheduled")  # scheduled, started, completed, cancelled
    calendly_uuid: str
    reminder_sent: bool = Field(default=False)
    physio_notified: bool = Field(default=False)

    physio_payment_status: str | None = None
    physio_payment_method: str | None = None
