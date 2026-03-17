"""State machine handlers for WhatsApp bot conversation flow."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re

from sqlmodel import Session, select, func

from app.core.config import settings
from app.models import Therapist, TherapistEventType, TherapistSpecialty
from app.services.booking_intents import create_booking_intent
from app.services.bot import menus, states
from app.services.bot.helpers import (
    get_conversation_data,
    reset_conversation,
    update_conversation_data,
    validate_comma_separated_choices,
    validate_numbered_choice,
)
from app.services.matching import match_therapist


logger = logging.getLogger(__name__)
GREETING_KEYWORDS = {"hi", "hello", "hey", "menu", "reset", "start"}
FEMALE_SPECIALTY_KEYWORDS = ("women", "female")
SUPPORTED_BOOKING_DURATIONS = (45, 30)


def _extract_name(body: str) -> str:
    """Extract a likely person name from natural-language input."""
    text = body.strip()
    if not text:
        return ""

    intro_patterns = [
        r"\b(?:my name is|i am|i'm|im|this is|name is)\b\s+(.+)",
    ]
    candidate = text
    for pattern in intro_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            break

    candidate = re.split(r"[.!?\n]", candidate, maxsplit=1)[0].strip()
    candidate = re.sub(
        r"\b(?:nice to meet you|thanks|thank you|pleasure to meet you)\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" -,:;")

    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", candidate)
    if not tokens:
        tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)

    return " ".join(tokens[:4]).title()


def _get_preferred_therapist_name(client, db: Session) -> str | None:
    """Get display name of client's preferred therapist, or None."""
    if not client.preferred_therapist_id:
        return None
    therapist = db.get(Therapist, client.preferred_therapist_id)
    return therapist.display_name if therapist else None


def _return_to_main_menu_with_message(
    client, db: Session, message: str
) -> tuple[str, str]:
    """Reset conversation and return main menu prefixed with a message."""
    reset_conversation(client, db)
    therapist_name = _get_preferred_therapist_name(client, db)
    can_manage_booking = _can_manage_booking(client, db) if client.name else False
    menu = menus.build_main_menu(client.name, therapist_name, can_manage_booking=can_manage_booking)
    return (states.IDLE, f"{message}\n\n{menu}")


def _list_active_therapists(db: Session) -> list[Therapist]:
    """Return active therapists in deterministic order."""
    return list(
        db.exec(
            select(Therapist)
            .where(Therapist.is_active == True)  # noqa: E712
            .order_by(Therapist.display_name.asc(), Therapist.id.asc())
        ).all()
    )


def _can_manage_booking(client, db: Session) -> bool:
    """Return True if client has at least one upcoming scheduled session."""
    if not client.id:
        return False
    from app.services.bot.reschedule import has_upcoming_sessions

    return has_upcoming_sessions(db, client.id)


def _list_visible_specialties(db: Session) -> list[TherapistSpecialty]:
    """Return active specialties excluding women/female labels (covered by dedicated option)."""
    specialties = db.exec(
        select(TherapistSpecialty)
        .where(TherapistSpecialty.is_active == True)  # noqa: E712
        .order_by(TherapistSpecialty.name)
    ).all()
    return [
        specialty
        for specialty in specialties
        if not any(keyword in (specialty.name or "").lower() for keyword in FEMALE_SPECIALTY_KEYWORDS)
    ]


def _get_womens_health_specialty(db: Session) -> TherapistSpecialty | None:
    """Return active Women's Health specialty if present."""
    return db.exec(
        select(TherapistSpecialty).where(
            func.lower(TherapistSpecialty.name) == "women's health",
            TherapistSpecialty.is_active == True,  # noqa: E712
        )
    ).first()


def _schedule_booking_link_followups(
    *,
    client_id: int,
    therapist_id: int,
    duration_minutes: int,
    therapist_name: str,
    scheduling_url: str,
) -> None:
    """Schedule booking-link follow-ups (1h + 6h) via APScheduler when enabled."""
    if not settings.booking_followup_enabled:
        return

    first_delay = max(0, settings.booking_followup_first_delay_seconds)
    second_delay = max(first_delay + 1, settings.booking_followup_second_delay_seconds)
    link_sent_at = datetime.now(timezone.utc).isoformat()

    try:
        from app.scheduler import schedule_booking_followup

        followups = (
            (1, first_delay),
            (2, second_delay),
        )
        for stage, delay_seconds in followups:
            schedule_booking_followup(
                client_id=client_id,
                therapist_id=therapist_id,
                duration_minutes=duration_minutes,
                therapist_name=therapist_name,
                scheduling_url=scheduling_url,
                link_sent_at_iso=link_sent_at,
                stage=stage,
                delay_seconds=delay_seconds,
            )
    except Exception:
        logger.exception(
            "Failed to schedule booking follow-up tasks client_id=%s therapist_id=%s",
            client_id,
            therapist_id,
        )


def _direct_booking_completion(
    *,
    client,
    db: Session,
    therapist: Therapist,
    duration_minutes: int,
    scheduling_url: str,
) -> tuple[str, str]:
    """Persist preference, schedule follow-up tasks, and return final booking-link message."""
    client.preferred_therapist_id = therapist.id
    db.add(client)
    event_type = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist.id,
            TherapistEventType.duration_minutes == duration_minutes,
            TherapistEventType.is_active == True,  # noqa: E712
        )
    ).first()
    if event_type:
        create_booking_intent(
            db,
            therapist_id=therapist.id,
            client_id=client.id,
            client_phone_e164=client.phone_e164,
            duration_minutes=duration_minutes,
            calendly_event_type_uri=event_type.calendly_event_type_uri,
            scheduling_url=event_type.scheduling_url,
            source="whatsapp",
        )
    db.commit()

    _schedule_booking_link_followups(
        client_id=client.id,
        therapist_id=therapist.id,
        duration_minutes=duration_minutes,
        therapist_name=therapist.display_name,
        scheduling_url=scheduling_url,
    )

    reset_conversation(client, db)
    return (
        states.IDLE,
        menus.build_booking_complete_message(scheduling_url, therapist.display_name),
    )


def _run_matching_and_build_confirmation(client, db: Session) -> tuple[str, str]:
    """Run deterministic matching and return confirmation prompt."""
    conv_data = get_conversation_data(client)
    matched_therapist = None
    is_rebooking = conv_data.get("rebooking", False)

    if is_rebooking and client.preferred_therapist_id:
        matched_therapist = db.exec(
            select(Therapist).where(
                Therapist.id == client.preferred_therapist_id,
                Therapist.is_active == True,  # noqa: E712
            )
        ).first()
        if not matched_therapist:
            is_rebooking = False

    fallback_level = 0
    if not is_rebooking or not matched_therapist:
        result = match_therapist(
            db=db,
            client_id=client.id,
            specialty_id=conv_data.get("specialty_id"),
            duration=conv_data.get("duration", 30),
            time_band=conv_data.get("time_band"),
            preferred_days=conv_data.get("days"),
            preferred_therapist_id=client.preferred_therapist_id,
            exclude_therapist_id=conv_data.get("exclude_therapist_id"),
            prefer_female=conv_data.get("prefer_female", False),
            require_specialty=conv_data.get("require_specialty", False),
            require_time_band=True,
        )
        if result is None:
            return _return_to_main_menu_with_message(
                client,
                db,
                "Sorry, we couldn't find an available therapist that matches your preferences right now.",
            )
        matched_therapist = result.therapist
        fallback_level = result.fallback_level

    update_conversation_data(
        client,
        matched_therapist_id=matched_therapist.id,
        fallback_level=fallback_level,
    )
    db.add(client)
    db.commit()

    specialty_id = conv_data.get("specialty_id")
    specialty_name = None
    if specialty_id is not None:
        specialty = db.exec(
            select(TherapistSpecialty).where(TherapistSpecialty.id == specialty_id)
        ).first()
        specialty_name = specialty.name if specialty else None
    if conv_data.get("prefer_female") and not specialty_name:
        specialty_name = "Female therapist"

    confirmation_menu = menus.build_match_confirmation_menu(
        therapist_name=matched_therapist.display_name,
        duration=conv_data.get("duration", 30),
        specialty=specialty_name,
        time_band=conv_data.get("time_band", states.TIME_BAND_WEEKDAY_DAY),
        fallback_level=fallback_level,
    )
    return (states.AWAITING_MATCH_CONFIRM, confirmation_menu)


def check_global_keywords(
    client, body: str, db: Session
) -> tuple[str, str] | None:
    """
    Check for global keywords that work from any conversation state.

    Returns (next_state, response_text) if a keyword matched, or None.
    """
    body_stripped = body.strip()

    if body_stripped in GREETING_KEYWORDS:
        client.conversation_data = None
        if not client.name:
            return (states.AWAITING_NAME, menus.build_welcome_menu())
        therapist_name = _get_preferred_therapist_name(client, db)
        can_manage_booking = _can_manage_booking(client, db)
        return (
            states.IDLE,
            menus.build_main_menu(client.name, therapist_name, can_manage_booking=can_manage_booking),
        )

    if body_stripped == "book":
        client.conversation_data = None
        if client.name:
            can_manage_booking = _can_manage_booking(client, db)
            return (
                states.AWAITING_BOOKING_PATH,
                menus.build_booking_path_menu(client.name, can_manage_booking=can_manage_booking),
            )
        return (states.AWAITING_NAME, menus.build_welcome_menu())

    if any(keyword in body for keyword in ["reschedule", "cancel"]):
        client.conversation_data = None
        return handle_reschedule_request(client, body, db)

    return None


def handle_idle(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle IDLE state — process main menu numbered choices.

    Menu varies by client type:
    - New client (no name): input treated as name
    - Returning client: smart match / by-name / reschedule
    - Returning client with preferred therapist: rebook / smart / by-name / reschedule
    """
    has_preferred = bool(client.name and client.preferred_therapist_id)
    has_name = bool(client.name)
    can_manage_booking = _can_manage_booking(client, db) if has_name else False

    if has_preferred:
        valid_choices = [1, 2, 3, 4] if can_manage_booking else [1, 2, 3]
        choice = validate_numbered_choice(body, valid_choices)
        if choice == 1:
            update_conversation_data(
                client,
                rebooking=True,
                book_by_name=True,
                selected_therapist_id=client.preferred_therapist_id,
            )
            db.add(client)
            db.commit()
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))
        if choice == 2:
            update_conversation_data(
                client,
                exclude_therapist_id=client.preferred_therapist_id,
                rebooking=False,
                book_by_name=False,
            )
            db.add(client)
            db.commit()
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))
        if choice == 3:
            therapists = _list_active_therapists(db)
            if not therapists:
                return (states.IDLE, "Sorry, there are no active therapists available right now.")
            options = [(t.id, t.display_name) for t in therapists]
            update_conversation_data(
                client,
                book_by_name=True,
                therapist_options=options,
            )
            db.add(client)
            db.commit()
            return (states.AWAITING_THERAPIST_PICK, menus.build_therapist_pick_menu(options))
        if choice == 4 and can_manage_booking:
            return handle_reschedule_request(client, body, db)
    elif has_name:
        valid_choices = [1, 2, 3] if can_manage_booking else [1, 2]
        choice = validate_numbered_choice(body, valid_choices)
        if choice == 1:
            update_conversation_data(client, book_by_name=False, rebooking=False)
            db.add(client)
            db.commit()
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))
        if choice == 2:
            therapists = _list_active_therapists(db)
            if not therapists:
                return (states.IDLE, "Sorry, there are no active therapists available right now.")
            options = [(t.id, t.display_name) for t in therapists]
            update_conversation_data(
                client,
                book_by_name=True,
                therapist_options=options,
            )
            db.add(client)
            db.commit()
            return (states.AWAITING_THERAPIST_PICK, menus.build_therapist_pick_menu(options))
        if choice == 3 and can_manage_booking:
            return handle_reschedule_request(client, body, db)
    else:
        return (states.AWAITING_NAME, menus.build_welcome_menu())

    therapist_name = _get_preferred_therapist_name(client, db)
    return (
        states.IDLE,
        menus.build_main_menu(client.name, therapist_name, can_manage_booking=can_manage_booking),
    )


def handle_awaiting_booking_path(client, body: str, db: Session) -> tuple[str, str]:
    """Handle booking-path choice after collecting official name."""
    can_manage_booking = _can_manage_booking(client, db)
    valid_choices = [1, 2, 3] if can_manage_booking else [1, 2]
    choice = validate_numbered_choice(body, valid_choices)
    if choice is None:
        return (
            states.AWAITING_BOOKING_PATH,
            menus.build_invalid_input_message([str(choice) for choice in valid_choices]),
        )

    if choice == 1:
        update_conversation_data(client, book_by_name=False, rebooking=False)
        db.add(client)
        db.commit()
        return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))

    if choice == 2:
        therapists = _list_active_therapists(db)
        if not therapists:
            return (states.IDLE, "Sorry, there are no active therapists available right now.")
        options = [(t.id, t.display_name) for t in therapists]
        update_conversation_data(
            client,
            book_by_name=True,
            therapist_options=options,
        )
        db.add(client)
        db.commit()
        return (states.AWAITING_THERAPIST_PICK, menus.build_therapist_pick_menu(options))

    if can_manage_booking and choice == 3:
        return handle_reschedule_request(client, body, db)

    return (
        states.AWAITING_BOOKING_PATH,
        menus.build_invalid_input_message([str(choice) for choice in valid_choices]),
    )


def handle_awaiting_name(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_NAME state - validate and save client name.

    Validation:
    - Must be at least 2 characters
    - Cannot be only digits
    """
    name = _extract_name(body)

    if len(name) < 2:
        return (
            states.AWAITING_NAME,
            "Please enter a valid full name (at least 2 characters).",
        )

    if name.isdigit():
        return (states.AWAITING_NAME, "Please enter your name, not a number.")

    client.name = name
    db.add(client)
    db.commit()
    can_manage_booking = _can_manage_booking(client, db)
    return (
        states.AWAITING_BOOKING_PATH,
        menus.build_booking_path_menu(name, can_manage_booking=can_manage_booking),
    )


def handle_awaiting_therapist_pick(client, body: str, db: Session) -> tuple[str, str]:
    """Handle deterministic therapist selection for book-by-name flow."""
    conv_data = get_conversation_data(client)
    options = conv_data.get("therapist_options") or []
    if not options:
        therapists = _list_active_therapists(db)
        options = [(t.id, t.display_name) for t in therapists]
        if not options:
            reset_conversation(client, db)
            return (states.IDLE, "Sorry, there are no active therapists available right now.")
        update_conversation_data(client, therapist_options=options, book_by_name=True)
        db.add(client)
        db.commit()

    valid_choices = list(range(1, len(options) + 1))
    choice = validate_numbered_choice(body, valid_choices)
    if choice is None:
        return (
            states.AWAITING_THERAPIST_PICK,
            menus.build_invalid_input_message([str(c) for c in valid_choices]),
        )

    selected_therapist_id = int(options[choice - 1][0])
    update_conversation_data(
        client,
        selected_therapist_id=selected_therapist_id,
        book_by_name=True,
    )
    db.add(client)
    db.commit()
    return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))


def handle_awaiting_duration(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_DURATION state - validate and save session duration.

    Valid choices: 1 (45min), 2 (30min)
    """
    choice = validate_numbered_choice(body, [1, 2])

    if choice is None:
        return (
            states.AWAITING_DURATION,
            menus.build_invalid_input_message(["1", "2"]),
        )

    duration_map = {1: 45, 2: 30}
    duration = duration_map[choice]
    conv_data = update_conversation_data(client, duration=duration)
    db.add(client)
    db.commit()

    if conv_data.get("book_by_name"):
        selected_therapist_id = conv_data.get("selected_therapist_id")
        therapist = (
            db.exec(
                select(Therapist).where(
                    Therapist.id == selected_therapist_id,
                    Therapist.is_active == True,  # noqa: E712
                )
            ).first()
            if selected_therapist_id
            else None
        )
        if not therapist:
            reset_conversation(client, db)
            return (states.IDLE, menus.build_error_message())

        event_type = db.exec(
            select(TherapistEventType).where(
                TherapistEventType.therapist_id == therapist.id,
                TherapistEventType.duration_minutes == duration,
                TherapistEventType.is_active == True,  # noqa: E712
            )
        ).first()
        if not event_type:
            event_types = list(
                db.exec(
                    select(TherapistEventType)
                    .where(
                        TherapistEventType.therapist_id == therapist.id,
                        TherapistEventType.duration_minutes.in_(SUPPORTED_BOOKING_DURATIONS),  # type: ignore[arg-type]
                        TherapistEventType.is_active == True,  # noqa: E712
                    )
                    .order_by(TherapistEventType.duration_minutes.desc(), TherapistEventType.id.asc())
                ).all()
            )
            duration_option_map: dict[int, str] = {}
            for candidate in event_types:
                if candidate.duration_minutes not in duration_option_map:
                    duration_option_map[candidate.duration_minutes] = candidate.scheduling_url

            if not duration_option_map:
                reset_conversation(client, db)
                return (
                    states.IDLE,
                    f"Sorry, {therapist.display_name} does not currently have bookable durations. "
                    "Please type 'menu' to restart.",
                )

            duration_options = sorted(duration_option_map.keys(), reverse=True)
            update_conversation_data(
                client,
                by_name_duration_options=[
                    {"duration_minutes": minutes, "scheduling_url": duration_option_map[minutes]}
                    for minutes in duration_options
                ],
                by_name_duration_therapist_id=therapist.id,
            )
            db.add(client)
            db.commit()
            return (
                states.AWAITING_BY_NAME_DURATION_OPTIONS,
                menus.build_by_name_available_duration_menu(therapist.display_name, duration_options),
            )

        return _direct_booking_completion(
            client=client,
            db=db,
            therapist=therapist,
            duration_minutes=duration,
            scheduling_url=event_type.scheduling_url,
        )

    return (states.AWAITING_MATCH_PREFERENCE, menus.build_match_preference_menu())


def handle_awaiting_by_name_duration_options(client, body: str, db: Session) -> tuple[str, str]:
    """Handle alternate duration selection when selected therapist lacks requested duration."""
    conv_data = get_conversation_data(client)
    options = conv_data.get("by_name_duration_options") or []
    therapist_id = conv_data.get("by_name_duration_therapist_id")
    therapist = db.get(Therapist, therapist_id) if therapist_id else None
    if not options or not therapist:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    valid_choices = list(range(1, len(options) + 1))
    choice = validate_numbered_choice(body, valid_choices)
    if choice is None:
        durations = [int(option["duration_minutes"]) for option in options]
        return (
            states.AWAITING_BY_NAME_DURATION_OPTIONS,
            menus.build_by_name_available_duration_menu(therapist.display_name, durations),
        )

    selected = options[choice - 1]
    duration_minutes = int(selected["duration_minutes"])
    scheduling_url = str(selected["scheduling_url"])

    update_conversation_data(client, duration=duration_minutes)
    db.add(client)
    db.commit()
    return _direct_booking_completion(
        client=client,
        db=db,
        therapist=therapist,
        duration_minutes=duration_minutes,
        scheduling_url=scheduling_url,
    )


def handle_awaiting_match_preference(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle match-preference step for smart match.

    Options:
    1) Female therapist
    2) Women's Health specialization
    3) No preference
    """
    choice = validate_numbered_choice(body, [1, 2, 3])
    if choice is None:
        return (
            states.AWAITING_MATCH_PREFERENCE,
            menus.build_invalid_input_message(["1", "2", "3"]),
        )

    prefer_female = False
    specialty_id = None
    require_specialty = False

    if choice == 1:
        prefer_female = True
    elif choice == 2:
        womens_health = _get_womens_health_specialty(db)
        if not womens_health:
            return _return_to_main_menu_with_message(
                client,
                db,
                "Sorry, we don't have Women's Health specialists available right now.",
            )
        specialty_id = womens_health.id
        require_specialty = True

    update_conversation_data(
        client,
        specialty_id=specialty_id,
        prefer_female=prefer_female,
        require_specialty=require_specialty,
    )
    db.add(client)
    db.commit()
    return (states.AWAITING_TIME_BAND, menus.build_time_band_menu())


def handle_awaiting_specialty(client, body: str, db: Session) -> tuple[str, str]:
    """Legacy alias for match-preference step."""
    return handle_awaiting_match_preference(client, body, db)


def handle_awaiting_time_band(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_TIME_BAND state - validate and save time preference.

    Valid choices:
    1 = weekday day (9-5)
    2 = weekday evening (5+)
    3 = weekend
    """
    choice = validate_numbered_choice(body, [1, 2, 3])

    if choice is None:
        return (
            states.AWAITING_TIME_BAND,
            menus.build_invalid_input_message(["1", "2", "3"]),
        )

    time_band_map = {
        1: states.TIME_BAND_WEEKDAY_DAY,
        2: states.TIME_BAND_WEEKDAY_EVENING,
        3: states.TIME_BAND_WEEKEND,
    }
    time_band = time_band_map[choice]
    update_conversation_data(client, time_band=time_band)
    db.add(client)
    db.commit()
    return _run_matching_and_build_confirmation(client, db)


def handle_awaiting_days(client, body: str, db: Session) -> tuple[str, str]:
    """
    Legacy handler for older in-flight sessions that still expect day input.

    New flow does not prompt for days, but we keep this for backward compatibility.
    """
    valid_days = [1, 2, 3, 4, 5, 6, 7]
    days = validate_comma_separated_choices(body, valid_days)
    if days is None or len(days) == 0:
        return (
            states.AWAITING_DAYS,
            "Please enter valid day numbers (1-7), separated by commas.",
        )

    update_conversation_data(client, days=days)
    db.add(client)
    db.commit()
    return _run_matching_and_build_confirmation(client, db)


def handle_awaiting_match_confirm(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_MATCH_CONFIRM state - confirm match and provide booking link.

    Valid choices:
    1 - Confirm and get booking link
    2 - Start over with different preferences
    """
    choice = validate_numbered_choice(body, [1, 2])

    if choice is None:
        return (
            states.AWAITING_MATCH_CONFIRM,
            menus.build_invalid_input_message(["1", "2"]),
        )

    if choice == 2:
        reset_conversation(client, db)
        can_manage_booking = _can_manage_booking(client, db)
        return (
            states.AWAITING_BOOKING_PATH,
            menus.build_booking_path_menu(client.name or "", can_manage_booking=can_manage_booking),
        )

    conv_data = get_conversation_data(client)
    matched_therapist_id = conv_data.get("matched_therapist_id")
    duration = conv_data.get("duration")

    if not matched_therapist_id or not duration:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    therapist = db.exec(
        select(Therapist).where(
            Therapist.id == matched_therapist_id,
            Therapist.is_active == True,  # noqa: E712
        )
    ).first()
    if not therapist:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    event_type = db.exec(
        select(TherapistEventType).where(
            TherapistEventType.therapist_id == therapist.id,
            TherapistEventType.duration_minutes == duration,
            TherapistEventType.is_active == True,  # noqa: E712
        )
    ).first()
    if not event_type:
        reset_conversation(client, db)
        return (
            states.IDLE,
            "Sorry, this therapist doesn't have a booking link for that duration. "
            "Please try again or choose a different option.",
        )

    return _direct_booking_completion(
        client=client,
        db=db,
        therapist=therapist,
        duration_minutes=duration,
        scheduling_url=event_type.scheduling_url,
    )


def handle_reschedule_request(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle reschedule/cancel request - show upcoming sessions with links.

    Called when user sends keywords like "reschedule" or "cancel".
    """
    from app.services.bot.reschedule import get_upcoming_sessions_with_links

    upcoming_sessions = get_upcoming_sessions_with_links(db, client.id)
    return (states.IDLE, menus.build_reschedule_menu(upcoming_sessions))


HANDLER_MAP = {
    states.IDLE: handle_idle,
    states.AWAITING_NAME: handle_awaiting_name,
    states.AWAITING_BOOKING_PATH: handle_awaiting_booking_path,
    states.AWAITING_THERAPIST_PICK: handle_awaiting_therapist_pick,
    states.AWAITING_DURATION: handle_awaiting_duration,
    states.AWAITING_BY_NAME_DURATION_OPTIONS: handle_awaiting_by_name_duration_options,
    states.AWAITING_MATCH_PREFERENCE: handle_awaiting_match_preference,
    states.AWAITING_SPECIALTY: handle_awaiting_specialty,  # legacy
    states.AWAITING_TIME_BAND: handle_awaiting_time_band,
    states.AWAITING_DAYS: handle_awaiting_days,  # legacy
    states.AWAITING_MATCH_CONFIRM: handle_awaiting_match_confirm,
}
