"""Helpers for surfacing therapist-authored session clinical notes on list views."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.session_note import SessionNote


def normalize_note_text(note_text: str) -> str:
    normalized = note_text.replace("\r\n", "\n").replace("\r", "\n")
    if "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized


def clinical_note_preview(note_text: str, max_len: int = 140) -> str:
    collapsed = " ".join(normalize_note_text(note_text).split())
    if len(collapsed) <= max_len:
        return collapsed
    return f"{collapsed[: max_len - 1].rstrip()}\u2026"


def latest_session_note_by_session_id(
    db: Session,
    *,
    therapist_user_id: int,
    session_ids: list[int],
) -> dict[int, SessionNote]:
    """Latest note row per session for this therapist (by created_at desc)."""
    ids = [sid for sid in session_ids if sid is not None]
    if not ids:
        return {}
    notes = db.exec(
        select(SessionNote)
        .where(
            SessionNote.session_id.in_(ids),  # type: ignore[arg-type]
            SessionNote.author_user_id == therapist_user_id,
        )
        .order_by(SessionNote.created_at.desc())
    ).all()
    latest: dict[int, SessionNote] = {}
    for note in notes:
        sid = note.session_id
        if sid not in latest:
            latest[sid] = note
    return latest
