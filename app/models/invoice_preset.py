from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class InvoicePreset(SQLModel, table=True):
    """Admin-managed preset values used in invoice generation."""

    __tablename__ = "invoice_preset"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    preset_type: str = Field(index=True, max_length=40)  # diagnosis|special_note
    label: str = Field(max_length=120)
    value: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    is_active: bool = Field(default=True, index=True)
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc))
    updated_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc), index=True)
