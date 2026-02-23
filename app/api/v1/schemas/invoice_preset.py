"""Schemas for admin invoice preset management."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InvoicePresetType = Literal["diagnosis", "special_note"]


class InvoicePresetItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: InvoicePresetType
    label: str
    value: str
    is_active: bool
    sort_order: int
    updated_at: datetime


class InvoicePresetCreateRequest(BaseModel):
    type: InvoicePresetType
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2000)
    is_active: bool = True
    sort_order: int = 0


class InvoicePresetUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    value: str | None = Field(default=None, min_length=1, max_length=2000)
    is_active: bool | None = None
    sort_order: int | None = None
