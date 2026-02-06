"""State constants for conversation state machine."""

# State constants
IDLE = "IDLE"
AWAITING_NAME = "AWAITING_NAME"
AWAITING_DURATION = "AWAITING_DURATION"
AWAITING_SPECIALTY = "AWAITING_SPECIALTY"
AWAITING_TIME_BAND = "AWAITING_TIME_BAND"
AWAITING_DAYS = "AWAITING_DAYS"
AWAITING_MATCH_CONFIRM = "AWAITING_MATCH_CONFIRM"
AWAITING_REBOOK_CHOICE = "AWAITING_REBOOK_CHOICE"

# Time band constants
TIME_BAND_MORNING = "morning"  # 8-11
TIME_BAND_AFTERNOON = "afternoon"  # 11-16
TIME_BAND_EVENING = "evening"  # 16-20

# Day mapping (for menu display)
DAYS_MAP = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}
