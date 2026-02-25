# WhatsApp Bot Flow Decision Tree

This document captures the current WhatsApp bot runtime flow in two clean views:
- Diagram 1: request router and state dispatch
- Diagram 2: booking funnel details

## Diagram 1: Request router and state dispatch

```mermaid
flowchart TD
  IN[Inbound WhatsApp webhook] --> FROM{From present}
  FROM -- No --> ERR[Return error: missing From]
  FROM -- Yes --> PRE[Load or create client and log inbound]
  PRE --> BODY{Body empty or media only}
  BODY -- Yes --> GUIDE[Send text-only guidance; keep state]
  BODY -- No --> KW{Global keyword}

  KW -- menu hi reset start --> MENU{Client has name}
  MENU -- No --> ASKNAME[Show welcome prompt; state AWAITING_NAME]
  MENU -- Yes --> MAIN[Show main menu; state IDLE]
  KW -- book --> BOOKQ{Client has name}
  BOOKQ -- No --> ASKNAME[Move to AWAITING_NAME]
  BOOKQ -- Yes --> BOOKPATH[Move to AWAITING_BOOKING_PATH]
  KW -- reschedule cancel --> MANAGE[Show upcoming sessions with links; state IDLE]
  KW -- none --> STATE{Current state}

  STATE -->|IDLE| H_IDLE[handle_idle]
  STATE -->|AWAITING_NAME| H_NAME[handle_awaiting_name]
  STATE -->|AWAITING_BOOKING_PATH| H_PATH[handle_awaiting_booking_path]
  STATE -->|AWAITING_THERAPIST_PICK| H_PICK[handle_awaiting_therapist_pick]
  STATE -->|AWAITING_DURATION| H_DUR[handle_awaiting_duration]
  STATE -->|AWAITING_BY_NAME_DURATION_OPTIONS| H_DUR_OPT[handle_awaiting_by_name_duration_options]
  STATE -->|AWAITING_SPECIALTY| H_SPEC[handle_awaiting_specialty]
  STATE -->|AWAITING_TIME_BAND| H_TIME[handle_awaiting_time_band]
  STATE -->|AWAITING_MATCH_CONFIRM| H_CONFIRM[handle_awaiting_match_confirm]
  STATE -->|AWAITING_DAYS legacy| H_DAYS[handle_awaiting_days]
  STATE -->|unknown| H_IDLE
```

## Diagram 2: Booking funnel

```mermaid
flowchart LR
  PROFILE{Client profile}
  PROFILE -->|No name| NAME[Collect name]
  PROFILE -->|Name only| MENU_STD[Menu: Smart, By-name, optional Manage]
  PROFILE -->|Name plus preferred therapist| MENU_PREF[Menu: Rebook, Smart diff, By-name, optional Manage]
  NAME --> MENU_STD

  MENU_STD -->|Manage| MANAGE[Show sessions and links]
  MENU_PREF -->|Manage| MANAGE

  MENU_PREF -->|Rebook| DUR_PREF[Choose duration]
  DUR_PREF --> PREF_OK{Selected therapist has event type}
  PREF_OK -- No --> DUR_PREF
  PREF_OK -- Yes --> COMPLETE[Send booking link, save preferred therapist, reset to IDLE]

  MENU_STD -->|By-name| PICK[Choose therapist]
  MENU_PREF -->|By-name| PICK
  PICK --> DUR_NAME[Choose duration]
  DUR_NAME --> NAME_OK{Selected therapist has selected duration}
  NAME_OK -- No --> ALT_DUR[Show available durations for therapist]
  ALT_DUR --> ALT_PICK[Choose available duration]
  ALT_PICK --> COMPLETE
  NAME_OK -- Yes --> COMPLETE

  MENU_STD -->|Smart| DUR_SMART[Choose duration]
  MENU_PREF -->|Smart diff| DUR_SMART
  DUR_SMART --> SPEC[Choose female filter, dynamic specialty, or no request]
  SPEC --> TIME[Choose time band]
  TIME --> MATCH{Match found}
  MATCH -- No --> MENU_STD
  MATCH -- Yes --> CONFIRM{Confirm match}
  CONFIRM -- Start over --> BOOKPATH[Back to booking path menu]
  CONFIRM -- Confirm --> COMPLETE
```

## Notes

- Inbound handling is synchronous by default (`WHATSAPP_WEBHOOK_SYNC_ENABLED=true`).
- The user-facing reply is sent inline in the same webhook request cycle.
- Optional follow-up nudges can be queued in Celery after booking-link completion when enabled.
- For unnamed clients, name capture is strict prompt-first (`AWAITING_NAME`) before saving.
- `Reschedule / Cancel` menu options are shown only when upcoming sessions exist.
