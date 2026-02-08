"""State machine handlers for WhatsApp bot conversation flow."""

from sqlmodel import Session, select

from app.models import Therapist, TherapistSpecialty
from app.services.bot import menus, states
from app.services.bot.helpers import (
    get_conversation_data,
    reset_conversation,
    update_conversation_data,
    validate_comma_separated_choices,
    validate_numbered_choice,
)


GREETING_KEYWORDS = {"hi", "hello", "hey", "menu", "reset", "start"}


def _get_preferred_therapist_name(client, db: Session) -> str | None:
    """Get display name of client's preferred therapist, or None."""
    if not client.preferred_therapist_id:
        return None
    therapist = db.get(Therapist, client.preferred_therapist_id)
    return therapist.display_name if therapist else None


def check_global_keywords(
    client, body: str, db: Session
) -> tuple[str, str] | None:
    """
    Check for global keywords that work from any conversation state.

    Returns (next_state, response_text) if a keyword matched, or None.
    """
    body_stripped = body.strip()

    # Greetings / menu reset
    if body_stripped in GREETING_KEYWORDS:
        client.conversation_data = None
        therapist_name = _get_preferred_therapist_name(client, db)
        return (states.IDLE, menus.build_main_menu(client.name, therapist_name))

    # Book keyword
    if body_stripped == "book":
        client.conversation_data = None
        if client.name:
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name))
        return (states.AWAITING_NAME, menus.build_welcome_menu())

    # Reschedule / cancel keywords (substring match)
    if any(keyword in body for keyword in ["reschedule", "cancel"]):
        client.conversation_data = None
        return handle_reschedule_request(client, body, db)

    return None


def handle_idle(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle IDLE state — process main menu numbered choices.

    Menu varies by client type:
    - New client (no name): any input → ask for name
    - Returning client (has name): 1=Book, 2=Reschedule
    - Returning client with preferred therapist: 1=Rebook, 2=Different, 3=Reschedule
    """
    has_preferred = client.name and client.preferred_therapist_id
    has_name = client.name

    if has_preferred:
        # 3-option menu: Rebook / Different / Reschedule
        choice = validate_numbered_choice(body, [1, 2, 3])
        if choice == 1:
            update_conversation_data(client, rebooking=True)
            db.add(client)
            db.commit()
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name))
        elif choice == 2:
            client.preferred_therapist_id = None
            db.add(client)
            db.commit()
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name))
        elif choice == 3:
            return handle_reschedule_request(client, body, db)
    elif has_name:
        # 2-option menu: Book / Reschedule
        choice = validate_numbered_choice(body, [1, 2])
        if choice == 1:
            return (states.AWAITING_DURATION, menus.build_duration_menu(client.name))
        elif choice == 2:
            return handle_reschedule_request(client, body, db)
    else:
        # New client — treat input as name directly
        return handle_awaiting_name(client, body, db)

    # Invalid choice — re-show main menu
    therapist_name = _get_preferred_therapist_name(client, db)
    return (states.IDLE, menus.build_main_menu(client.name, therapist_name))


def handle_awaiting_name(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_NAME state - validate and save client name.

    Validation:
    - Must be at least 2 characters
    - Cannot be only digits
    """
    name = body.strip().title()

    # Validate name
    if len(name) < 2:
        return (
            states.AWAITING_NAME,
            "Please enter a valid name (at least 2 characters).",
        )

    if name.isdigit():
        return (states.AWAITING_NAME, "Please enter your name, not a number.")

    # Save name to client
    client.name = name
    db.add(client)
    db.commit()

    return (states.AWAITING_DURATION, menus.build_duration_menu(name))


def handle_awaiting_duration(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_DURATION state - validate and save session duration.

    Valid choices: 1 (30min), 2 (45min), 3 (60min)
    """
    choice = validate_numbered_choice(body, [1, 2, 3])

    if choice is None:
        return (
            states.AWAITING_DURATION,
            menus.build_invalid_input_message(["1", "2", "3"]),
        )

    # Map choice to duration
    duration_map = {1: 30, 2: 45, 3: 60}
    duration = duration_map[choice]

    # Save to conversation data
    update_conversation_data(client, duration=duration)
    db.add(client)
    db.commit()

    # Get active specialties (ordered consistently by name)
    specialties = db.exec(
        select(TherapistSpecialty)
        .where(TherapistSpecialty.is_active == True)  # noqa: E712
        .order_by(TherapistSpecialty.name)
    ).all()

    if not specialties:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    return (states.AWAITING_SPECIALTY, menus.build_specialty_menu(list(specialties)))


def handle_awaiting_specialty(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_SPECIALTY state - validate and save specialty selection.

    Validates choice against active specialties in database.
    """
    # Get active specialties (ordered consistently by name)
    specialties = db.exec(
        select(TherapistSpecialty)
        .where(TherapistSpecialty.is_active == True)  # noqa: E712
        .order_by(TherapistSpecialty.name)
    ).all()
    specialty_list = list(specialties)

    if not specialty_list:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    # Validate choice
    valid_choices = list(range(1, len(specialty_list) + 1))
    choice = validate_numbered_choice(body, valid_choices)

    if choice is None:
        return (
            states.AWAITING_SPECIALTY,
            menus.build_invalid_input_message([str(i) for i in valid_choices]),
        )

    # Get selected specialty
    selected_specialty = specialty_list[choice - 1]  # Convert to 0-indexed

    # Save to conversation data
    update_conversation_data(client, specialty_id=selected_specialty.id)
    db.add(client)
    db.commit()

    return (states.AWAITING_TIME_BAND, menus.build_time_band_menu())


def handle_awaiting_time_band(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_TIME_BAND state - validate and save time preference.

    Valid choices: 1 (morning), 2 (afternoon), 3 (evening)
    """
    choice = validate_numbered_choice(body, [1, 2, 3])

    if choice is None:
        return (
            states.AWAITING_TIME_BAND,
            menus.build_invalid_input_message(["1", "2", "3"]),
        )

    # Map choice to time band
    time_band_map = {
        1: states.TIME_BAND_MORNING,
        2: states.TIME_BAND_AFTERNOON,
        3: states.TIME_BAND_EVENING,
    }
    time_band = time_band_map[choice]

    # Save to conversation data
    update_conversation_data(client, time_band=time_band)
    db.add(client)
    db.commit()

    return (states.AWAITING_DAYS, menus.build_days_menu())


def handle_awaiting_days(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle AWAITING_DAYS state - validate day selections and match therapist.

    Valid choices: 1-7 (Monday-Sunday), can be comma-separated
    After collecting days, performs therapist matching (stubbed in Phase 2).
    """
    # Validate day choices
    valid_days = [1, 2, 3, 4, 5, 6, 7]
    days = validate_comma_separated_choices(body, valid_days)

    if days is None or len(days) == 0:
        return (
            states.AWAITING_DAYS,
            "Please enter valid day numbers (1-7), separated by commas.\n"
            "Example: 1,3,5 for Monday, Wednesday, Friday",
        )

    # Save days to conversation data
    conv_data = update_conversation_data(client, days=days)
    db.add(client)
    db.commit()

    # Check if user is rebooking with their preferred therapist
    matched_therapist = None
    is_rebooking = conv_data.get("rebooking", False)
    if is_rebooking and client.preferred_therapist_id:
        # Use the preferred therapist for rebook shortcut
        matched_therapist = db.exec(
            select(Therapist).where(
                Therapist.id == client.preferred_therapist_id,
                Therapist.is_active == True,  # noqa: E712
            )
        ).first()

        # If preferred therapist is no longer active, fall back to matching
        if not matched_therapist:
            is_rebooking = False

    # STUB: Matching logic (Phase 3 will replace this)
    if not is_rebooking or not matched_therapist:
        # For now, just get the first active therapist
        matched_therapist = db.exec(
            select(Therapist).where(Therapist.is_active == True)  # noqa: E712
        ).first()

    if not matched_therapist:
        reset_conversation(client, db)
        return (
            states.IDLE,
            "Sorry, no therapists are currently available. Please try again later.",
        )

    # Save matched therapist to conversation data
    update_conversation_data(
        client, matched_therapist_id=matched_therapist.id, fallback_level=0
    )
    db.add(client)
    db.commit()

    # Get specialty name for display
    specialty_id = conv_data.get("specialty_id")
    specialty = db.exec(
        select(TherapistSpecialty).where(TherapistSpecialty.id == specialty_id)
    ).first()
    specialty_name = specialty.name if specialty else "Unknown"

    # Build confirmation menu
    confirmation_menu = menus.build_match_confirmation_menu(
        therapist_name=matched_therapist.display_name,
        duration=conv_data["duration"],
        specialty=specialty_name,
        time_band=conv_data["time_band"],
        days=days,
        fallback_level=0,
    )

    return (states.AWAITING_MATCH_CONFIRM, confirmation_menu)


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

    # Choice 2: Start over
    if choice == 2:
        reset_conversation(client, db)
        return (states.AWAITING_DURATION, menus.build_duration_menu(client.name or ""))

    # Choice 1: Confirm match
    conv_data = get_conversation_data(client)
    matched_therapist_id = conv_data.get("matched_therapist_id")
    duration = conv_data.get("duration")

    if not matched_therapist_id or not duration:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    # Get therapist details
    therapist = db.exec(
        select(Therapist).where(Therapist.id == matched_therapist_id)
    ).first()

    if not therapist:
        reset_conversation(client, db)
        return (states.IDLE, menus.build_error_message())

    # STUB: Generate Calendly link (Phase 3 will replace this)
    # In Phase 3, this will call the Calendly service to get a real scheduling URL
    calendly_link = f"https://calendly.com/stub-therapist-{therapist.id}-{duration}min"

    # Save preferred therapist for future rebookings
    client.preferred_therapist_id = matched_therapist_id
    db.add(client)
    db.commit()

    # Reset conversation state
    reset_conversation(client, db)

    return (
        states.IDLE,
        menus.build_booking_complete_message(calendly_link, therapist.display_name),
    )


def handle_reschedule_request(client, body: str, db: Session) -> tuple[str, str]:
    """
    Handle reschedule/cancel request - show upcoming sessions with links.

    Called when user sends keywords like "reschedule" or "cancel".
    """
    # Import here to avoid circular dependency
    from app.services.bot.reschedule import get_upcoming_sessions_with_links

    upcoming_sessions = get_upcoming_sessions_with_links(db, client.id)
    return (states.IDLE, menus.build_reschedule_menu(upcoming_sessions))


# Handler map - maps state to handler function
HANDLER_MAP = {
    states.IDLE: handle_idle,
    states.AWAITING_NAME: handle_awaiting_name,
    states.AWAITING_DURATION: handle_awaiting_duration,
    states.AWAITING_SPECIALTY: handle_awaiting_specialty,
    states.AWAITING_TIME_BAND: handle_awaiting_time_band,
    states.AWAITING_DAYS: handle_awaiting_days,
    states.AWAITING_MATCH_CONFIRM: handle_awaiting_match_confirm,
}
