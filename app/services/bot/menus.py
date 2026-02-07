"""Menu text builders for WhatsApp bot IVR."""

from app.models import TherapistSpecialty
from app.services.bot.states import DAYS_MAP


def build_welcome_menu() -> str:
    """Build welcome message asking for user's name."""
    return (
        "Welcome to our Physiotherapy Clinic! 👋\n\n"
        "To help you book an appointment, what's your name?"
    )


def build_duration_menu(name: str) -> str:
    """Build menu for session duration selection."""
    return (
        f"Thanks, {name}! 😊\n\n"
        "How long would you like your session to be?\n\n"
        "1️⃣ 30 minutes\n"
        "2️⃣ 45 minutes\n"
        "3️⃣ 60 minutes\n\n"
        "Please reply with 1, 2, or 3."
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

    lines.append(f"\nPlease reply with a number (1-{len(specialties)}).")

    return "\n".join(lines)


def build_time_band_menu() -> str:
    """Build menu for time preference selection."""
    return (
        "When would you prefer your appointment?\n\n"
        "1️⃣ Morning (8:00 AM - 11:00 AM)\n"
        "2️⃣ Afternoon (11:00 AM - 4:00 PM)\n"
        "3️⃣ Evening (4:00 PM - 8:00 PM)\n\n"
        "Please reply with 1, 2, or 3."
    )


def build_days_menu() -> str:
    """Build menu for day of week selection."""
    return (
        "Which days work best for you?\n\n"
        "1️⃣ Monday\n"
        "2️⃣ Tuesday\n"
        "3️⃣ Wednesday\n"
        "4️⃣ Thursday\n"
        "5️⃣ Friday\n"
        "6️⃣ Saturday\n"
        "7️⃣ Sunday\n\n"
        "You can select multiple days by separating them with commas.\n"
        "Example: 1,3,5 for Monday, Wednesday, Friday"
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
    specialty: str,
    time_band: str,
    days: list[int],
    fallback_level: int = 0,
) -> str:
    """Build menu showing matched therapist and asking for confirmation."""
    # Build days string
    day_names = [DAYS_MAP[d] for d in sorted(days)]
    days_str = ", ".join(day_names)

    # Build time band string
    time_map = {
        "morning": "Morning (8-11 AM)",
        "afternoon": "Afternoon (11 AM-4 PM)",
        "evening": "Evening (4-8 PM)",
    }
    time_str = time_map.get(time_band, time_band)

    message = "Great! We've found a therapist for you:\n\n"
    message += f"👨‍⚕️ Therapist: {therapist_name}\n"
    message += f"📋 Specialty: {specialty}\n"
    message += f"⏱️ Duration: {duration} minutes\n"
    message += f"🕐 Preferred time: {time_str}\n"
    message += f"📅 Preferred days: {days_str}\n"

    if fallback_level > 0:
        message += (
            f"\n⚠️ Note: This match used relaxed criteria (level {fallback_level}).\n"
        )

    message += "\nWould you like to proceed with booking?\n\n"
    message += "1️⃣ Yes, book with this therapist\n"
    message += "2️⃣ No, start over with different preferences\n\n"
    message += "Please reply with 1 or 2."

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
            "To book a new appointment, just send 'hi' or 'hello'!"
        )

    lines = ["Here are your upcoming appointments:\n"]

    for idx, session in enumerate(upcoming_sessions, 1):
        lines.append(f"\n{idx}. {session['start_time']}")
        lines.append(f"   Therapist: {session['therapist_name']}")
        lines.append(f"   📝 Reschedule: {session['reschedule_url']}")
        lines.append(f"   ❌ Cancel: {session['cancel_url']}")

    lines.append("\n💡 Click the links above to manage your appointments.")

    return "\n".join(lines)


def build_booking_complete_message(calendly_link: str, therapist_name: str) -> str:
    """Build final message with booking link."""
    return (
        f"Perfect! 🎉\n\n"
        f"Click the link below to choose your preferred time with {therapist_name}:\n\n"
        f"{calendly_link}\n\n"
        f"You'll receive a confirmation once your appointment is booked.\n\n"
        f"Need help? Just send 'reschedule' to manage your appointments."
    )


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
