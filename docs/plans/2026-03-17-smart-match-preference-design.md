# Smart Match Preference Step Design (2026-03-17)

## Summary
Replace the specialty-selection step in the Smart Match flow with a simpler preference step:
Duration -> Preference (female / women's health / no preference) -> Time band -> Match.
Women’s Health requires the Women’s Health specialty. If no match is found for the selected
preference + time band, return the user to the main menu.

## Goals
- Remove the general specialty picker from Smart Match.
- Add a preference step with three choices:
  - Female therapist
  - Women’s Health specialization
  - No preference
- Enforce time band for Smart Match (no time-band fallback).
- Enforce Women’s Health specialty when selected (no specialty fallback).
- Keep backward compatibility for in-flight sessions.

## Non-goals
- Changing non-Smart-Match flows.
- Reworking the matching algorithm beyond adding strictness flags.

## Current Flow (Smart Match)
Duration -> Specialty -> Time band -> Match confirm -> Booking link.

## Proposed Flow (Smart Match)
Duration -> Match Preference -> Time band -> Match confirm -> Booking link.

## State and Menu Changes
- Add a new state `AWAITING_MATCH_PREFERENCE`.
- Alias `AWAITING_SPECIALTY` to the same handler to avoid breaking in-flight sessions.
- Replace `build_specialty_menu` usage in Smart Match with a new
  `build_match_preference_menu`:
  1. Female therapist
  2. Women’s Health specialization
  3. No preference

## Matching Behavior
- Women’s Health option:
  - Resolve specialty by name "Women's Health".
  - Set `specialty_id` to that ID.
  - Pass `require_specialty=True`.
- Female option:
  - Use existing `prefer_female=True` hard filter.
- No preference option:
  - `prefer_female=False`, `specialty_id=None`.
- For all Smart Match requests:
  - Pass `require_time_band=True` so no time-band fallback occurs.

## Error Handling and User Messaging
- If the Women’s Health specialty is missing or no match is found under the selected
  preference + time band, respond with a friendly message and return to the main menu.
- If no therapists are active at all, use the existing "no therapists available" message
  and return to main menu.

## Backward Compatibility
- Treat `AWAITING_SPECIALTY` as `AWAITING_MATCH_PREFERENCE` to handle old in-flight sessions.

## Tests and Docs to Update
- `tests/test_bot_flow.py`: replace specialty step assertions with preference step.
- `tests/test_bot_handlers.py`: update handler behavior and add coverage for new options.
- `scripts/test_bot_flow.sh`: remove specialty step, add preference step.
- `docs/16-whatsapp-bot-flow-decision-tree.md`: update flow diagram and notes.

