"""Menu text builders for WhatsApp bot IVR."""

from app.models import TherapistSpecialty


def build_main_menu(client_name: str | None, therapist_name: str | None) -> str:
    """Build main menu based on client type."""
    if client_name and therapist_name:
        return (
            f"Welcome back, {client_name}! 👋\n\n"
            "How can we help you today?\n\n"
            f"1️⃣ Book again with {therapist_name}\n"
            "2️⃣ Smart match (different therapist)\n"
            "3️⃣ Book therapist by name\n"
            "4️⃣ Reschedule or cancel\n\n"
            "Reply with a number, or type 'book' anytime."
        )
    elif client_name:
        return (
            f"Welcome back, {client_name}! 👋\n\n"
            "How can we help you today?\n\n"
            "1️⃣ Smart match (recommended)\n"
            "2️⃣ Book therapist by name\n"
            "3️⃣ Reschedule or cancel\n\n"
            "Reply with a number, or type 'book' anytime."
        )
    else:
        return "Welcome to Movement Clinic! 👋\n\nTo get started, please tell us your full official name as per HKID (for receipts)."


def build_welcome_menu() -> str:
    """Build welcome message asking for user's name."""
    return (
        "Welcome to Movement Clinic! 👋\n\n"
        "Please tell us your full official name as per HKID "
        "(this is used for receipt generation)."
    )


def build_booking_path_menu(name: str) -> str:
    """Build booking-path menu for clients without a preferred therapist shortcut."""
    return (
        f"Thanks, {name}! 😊\n\n"
        "How would you like to book?\n\n"
        "1️⃣ Smart match (recommended)\n"
        "2️⃣ Book therapist by name\n"
        "3️⃣ Reschedule or cancel\n\n"
        "Please reply with 1, 2, or 3. `Menu` to go back to main menu."
    )


def build_duration_menu(name: str) -> str:
    """Build menu for session duration selection."""
    return (
        f"Thanks, {name}! 😊\n\n"
        "How long would you like your session to be?\n\n"
        "1️⃣ 45 minutes - Standard Appointment\n"
        "2️⃣ 30 minutes\n"
        "Please reply with 1 or 2. `Menu` to go back to main menu."
    )


def build_specialty_menu(specialties: list[TherapistSpecialty]) -> str:
    """Build menu for specialty selection from active specialties."""
    if not specialties:
        return "Sorry, no specialties are currently available. Please try again later."

    lines = ["What type of physiotherapy do you need?\n"]

    for idx, specialty in enumerate(specialties, 1):
        emoji = _get_specialty_emoji(idx)
        lines.append(f"{emoji} {specialty.name}")
        if specialty.description:
            lines.append(f"   {specialty.description}")

    no_pref_idx = len(specialties) + 1
    lines.append(f"{_get_specialty_emoji(no_pref_idx)} No special request")

    lines.append(
        f"\nPlease reply with a number (1-{no_pref_idx}). `Menu` to go back to main menu."
    )

    return "\n".join(lines)


def build_time_band_menu() -> str:
    """Build menu for time preference selection."""
    return (
        "When would you prefer your appointment?\n\n"
        "1️⃣ Weekday day session (9:00 AM - 6:00 PM)\n"
        "2️⃣ Weekday evening session (6:00 PM onwards)\n"
        "3️⃣ Weekend session\n\n"
        "Please reply with 1, 2, or 3. `Menu` to go back to main menu."
    )


def build_rebook_menu(client_name: str, therapist_name: str) -> str:
    """Build menu for returning clients who want to rebook with same therapist."""
    return (
        f"Welcome back, {client_name}! 😊\n\n"
        f"Would you like to book another session with {therapist_name}?\n\n"
        "1️⃣ Yes, book with the same therapist\n"
        "2️⃣ No, I'd like to try a different therapist\n\n"
        "Please reply with 1 or 2."
    )


def build_match_confirmation_menu(
    therapist_name: str,
    duration: int,
    specialty: str | None,
    time_band: str,
    fallback_level: int = 0,
) -> str:
    """Build menu showing matched therapist and asking for confirmation."""
    # Build time band string
    time_map = {
        "weekday_day": "Weekday day (9 AM-6 PM)",
        "weekday_evening": "Weekday evening (6 PM onwards)",
        "weekend": "Weekend",
    }
    time_str = time_map.get(time_band, time_band)
    specialty_str = specialty or "No special request"

    message = f"Great! We've found a therapist for you:\n\n"
    message += f"👨‍⚕️ Therapist: {therapist_name}\n"
    message += f"📋 Specialty: {specialty_str}\n"
    message += f"⏱️ Duration: {duration} minutes\n"
    message += f"🕐 Preferred time: {time_str}\n"

    if fallback_level > 0:
        message += (
            f"\n⚠️ Note: This match used relaxed criteria (level {fallback_level}).\n"
        )

    message += "\nWould you like to proceed with booking?\n\n"
    message += "1️⃣ Yes, book with this therapist\n"
    message += "2️⃣ No, start over with different preferences\n\n"
    message += "Please reply with 1 or 2. `Menu` to go back to main menu."

    return message


def build_invalid_input_message(valid_options: list[str]) -> str:
    """Build error message for invalid input."""
    options_str = ", ".join(valid_options)
    return f"Sorry, I didn't understand that. 😕\n\nPlease reply with: {options_str}"


def build_reschedule_menu(upcoming_sessions: list[dict]) -> str:
    """Build menu showing upcoming sessions with reschedule/cancel links."""
    if not upcoming_sessions:
        return (
            "You don't have any upcoming appointments. 📅\n\n"
            "To book a new appointment, just send 'menu' to return to the main menu!"
        )

    lines = ["Here are your upcoming appointments:\n"]

    for idx, session in enumerate(upcoming_sessions, 1):
        lines.append(f"\n{idx}. {session['start_time']}")
        lines.append(f"   Therapist: {session['therapist_name']}")
        reschedule_url = session.get("reschedule_url")
        cancel_url = session.get("cancel_url")
        if reschedule_url:
            lines.append(f"   📝 Reschedule: {reschedule_url}")
        else:
            lines.append("   📝 Reschedule: Please reply 'help reschedule' and admin will assist.")
        if cancel_url:
            lines.append(f"   ❌ Cancel: {cancel_url}")
        else:
            lines.append("   ❌ Cancel: Please reply 'help cancel' and admin will assist.")

    lines.append("\n💡 Click the links above to manage your appointments.")

    return "\n".join(lines)


def build_booking_complete_message(calendly_link: str, therapist_name: str) -> str:
    """Build final message with booking link."""
    return (
        f"Perfect! 🎉\n\n"
        f"Click the link below to choose your preferred time with {therapist_name}:\n\n"
        f"{calendly_link}\n\n"
        f"You'll receive a confirmation once your appointment is booked.\n\n"
        f"Need help? Send 'menu' for options or 'reschedule' to manage appointments."
    )


def build_therapist_pick_menu(therapists: list[tuple[int, str]]) -> str:
    """Build deterministic therapist selection menu for book-by-name flow."""
    if not therapists:
        return "Sorry, there are no active therapists available right now."

    lines = ["Choose your therapist:\n"]
    for idx, (_, display_name) in enumerate(therapists, 1):
        lines.append(f"{_get_specialty_emoji(idx)} {display_name}")

    lines.append(
        f"\nPlease reply with a number (1-{len(therapists)}). `Menu` to go back to main menu."
    )
    return "\n".join(lines)


def build_error_message() -> str:
    """Build generic error message when something goes wrong."""
    return (
        "Oops! Something went wrong. 😕\n\n"
        "Please try again or contact us for assistance."
    )


def _get_specialty_emoji(index: int) -> str:
    """Get emoji for specialty menu numbering."""
    emoji_map = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
    }
    return emoji_map.get(index, f"{index}.")
