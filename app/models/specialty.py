from __future__ import annotations

from sqlmodel import Field, SQLModel, UniqueConstraint


class TherapistSpecialty(SQLModel, table=True):
    """Admin-managed specialty categories (e.g., Sports Rehab, Orthopedic)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    is_active: bool = Field(default=True)


class TherapistSpecialtyMap(SQLModel, table=True):
    """Many-to-many mapping between therapists and specialties."""

    __tablename__ = "therapist_specialty_map"  # type: ignore
    __table_args__ = (UniqueConstraint("therapist_id", "specialty_id"),)  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    therapist_id: int = Field(foreign_key="therapist.id", index=True)
    specialty_id: int = Field(foreign_key="therapistspecialty.id", index=True)
