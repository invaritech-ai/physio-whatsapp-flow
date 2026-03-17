"""State constants for conversation state machine."""

# State constants
IDLE = "IDLE"
AWAITING_NAME = "AWAITING_NAME"
AWAITING_BOOKING_PATH = "AWAITING_BOOKING_PATH"
AWAITING_DURATION = "AWAITING_DURATION"
AWAITING_MATCH_PREFERENCE = "AWAITING_MATCH_PREFERENCE"
# Legacy state kept for in-flight conversations; mapped to match preference handler.
AWAITING_SPECIALTY = "AWAITING_SPECIALTY"
AWAITING_TIME_BAND = "AWAITING_TIME_BAND"
AWAITING_THERAPIST_PICK = "AWAITING_THERAPIST_PICK"
AWAITING_BY_NAME_DURATION_OPTIONS = "AWAITING_BY_NAME_DURATION_OPTIONS"
AWAITING_MATCH_CONFIRM = "AWAITING_MATCH_CONFIRM"
# Legacy state kept for in-flight conversations; new flow no longer prompts for days.
AWAITING_DAYS = "AWAITING_DAYS"

# Time band constants
TIME_BAND_WEEKDAY_DAY = "weekday_day"  # 09:00-18:00
TIME_BAND_WEEKDAY_EVENING = "weekday_evening"  # 18:00+
TIME_BAND_WEEKEND = "weekend"  # Saturday/Sunday
