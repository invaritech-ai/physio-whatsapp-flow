from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import field_validator
from sqlmodel import Session, SQLModel, select

from app.db.session import get_session
from app.models.appointment import Appointment
from app.models.session_note import SessionNote, SessionNoteBase
from app.models.user import User

router = APIRouter(prefix="/session-notes", tags=["session-notes"])


# --- Request/Response Schemas ---


class SessionNoteCreate(SessionNoteBase):
    """Request body for creating a session note."""

    @field_validator("note_text")
    @classmethod
    def note_text_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("note_text must not be empty")
        return v.strip()


class SessionNoteUpdate(SQLModel):
    """Request body for updating a session note (partial update).

    All fields optional — cannot derive from base.
    """

    physio_id: int | None = None
    note_text: str | None = None
    created_by: str | None = None

    @field_validator("note_text")
    @classmethod
    def note_text_not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("note_text must not be empty")
        return v.strip() if v else v


class SessionNoteRead(SessionNoteBase):
    """Response body for a session note."""

    id: int
    created_at: datetime


# --- Endpoints ---


@router.get("", response_model=list[SessionNoteRead])
def list_session_notes(
    appointment_id: int | None = Query(None, description="Filter notes by appointment ID"),
    physio_id: int | None = Query(None, description="Filter notes by physio ID"),
    db: Session = Depends(get_session),
):
    """List session notes filtered by appointment_id and/or physio_id.

    At least one filter parameter must be provided.
    """
    if appointment_id is None and physio_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one filter parameter (appointment_id or physio_id) must be provided",
        )

    statement = select(SessionNote)

    if appointment_id is not None:
        appointment = db.get(Appointment, appointment_id)
        if not appointment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Appointment {appointment_id} not found",
            )
        statement = statement.where(SessionNote.appointment_id == appointment_id)

    if physio_id is not None:
        physio = db.get(User, physio_id)
        if not physio:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Physio {physio_id} not found",
            )
        statement = statement.where(SessionNote.physio_id == physio_id)

    statement = statement.order_by(SessionNote.created_at)
    notes = db.exec(statement).all()
    return notes


@router.get("/{note_id}", response_model=SessionNoteRead)
def get_session_note(
    note_id: int,
    db: Session = Depends(get_session),
):
    """Get a single session note by ID."""
    note = db.get(SessionNote, note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session note {note_id} not found",
        )
    return note


@router.post("", response_model=SessionNoteRead, status_code=status.HTTP_201_CREATED)
def create_session_note(
    payload: SessionNoteCreate,
    db: Session = Depends(get_session),
):
    """Create a new session note for an appointment."""
    appointment = db.get(Appointment, payload.appointment_id)
    if not appointment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appointment {payload.appointment_id} not found",
        )

    note = SessionNote(
        appointment_id=payload.appointment_id,
        physio_id=payload.physio_id,
        note_text=payload.note_text,
        created_at=datetime.now(timezone.utc),
        created_by=payload.created_by,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.patch("/{note_id}", response_model=SessionNoteRead)
def update_session_note(
    note_id: int,
    payload: SessionNoteUpdate,
    db: Session = Depends(get_session),
):
    """Update an existing session note (partial update)."""
    note = db.get(SessionNote, note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session note {note_id} not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )

    for key, value in update_data.items():
        setattr(note, key, value)

    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session_note(
    note_id: int,
    db: Session = Depends(get_session),
):
    """Delete a session note."""
    note = db.get(SessionNote, note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session note {note_id} not found",
        )

    db.delete(note)
    db.commit()
