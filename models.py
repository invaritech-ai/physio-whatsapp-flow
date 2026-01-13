from typing import Optional
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True, unique=True)
    name: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(default="customer") # customer, physio, admin
    
    # State management for conversation flow
    conversation_state: str = Field(default="idle") # idle, awaiting_name, awaiting_email
    last_proposed_start: Optional[datetime] = None
    last_proposed_duration: Optional[int] = None

class Appointment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id")
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    status: str = Field(default="scheduled")  # scheduled, completed, cancelled
    calendly_uuid: str
    reminder_sent: bool = Field(default=False)
    physio_notified: bool = Field(default=False)
    
    # Relationships
    # customer: User = Relationship(back_populates="appointments")

class Payment(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    appointment_id: int = Field(foreign_key="appointment.id")
    amount: float
    status: str = Field(default="pending")  # pending, approved, rejected
    payment_method: str  # credit_card, fps
    proof_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
