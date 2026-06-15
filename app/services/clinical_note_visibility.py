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
    therapist_user_id: int | None,
    session_ids: list[int],
) -> dict[int, SessionNote]:
    """Latest note row per session (by created_at desc).

    When ``therapist_user_id`` is provided, only that author's notes are
    considered (therapist-scoped views). Pass ``None`` to consider notes from
    any author (admin views, matching the admin clinical-note read path).
    """
    ids = [sid for sid in session_ids if sid is not None]
    if not ids:
        return {}
    stmt = select(SessionNote).where(
        SessionNote.session_id.in_(ids),  # type: ignore[arg-type]
    )
    if therapist_user_id is not None:
        stmt = stmt.where(SessionNote.author_user_id == therapist_user_id)
    notes = db.exec(stmt.order_by(SessionNote.created_at.desc())).all()
    latest: dict[int, SessionNote] = {}
    for note in notes:
        sid = note.session_id
        if sid not in latest:
            latest[sid] = note
    return latest
