# Challenges And Issue Tracker

Last updated: 2026-02-12

## Status Legend
- `OPEN`: not fixed yet
- `IN_PROGRESS`: implementation started
- `BLOCKED`: waiting on external dependency
- `DONE`: fixed and verified

## Tracker
| ID | Area | Status | Priority | Issue | Current Impact | Verification |
|---|---|---|---|---|---|---|
| CH-001 | Matching | `OPEN` | High | Time-band/day preference is not enforced by matcher yet (availability-aware gating missing). | Therapist can be recommended even when no slot matches requested time/day. | Repro via bot flow: choose a band/day with no real slots and confirm recommendation still appears. |
| CH-002 | Notifications | `OPEN` | High | No WhatsApp confirmation is sent on Calendly `invitee.created` / `invitee.rescheduled` / `invitee.canceled`. | User gets booking link but no webhook-driven confirmation updates. | Trigger Calendly events and check outbound WhatsApp/message logs. |
| CH-003 | Webhooks | `DONE` | High | Therapist webhook self-service check/register was missing. | Hard to onboard therapists across mixed Calendly orgs. | `POST /api/v1/therapist/onboarding/calendly-webhook/check` and `/register`. |
| CH-004 | Webhooks | `DONE` | High | Reschedule event handling missing (`invitee.rescheduled`). | Rescheduled appointments not reflected reliably. | `tests/test_calendly_webhooks_rescheduled.py`. |
| CH-005 | Bot UX | `DONE` | Medium | Name capture accepted pleasantries as full name. | Poor name quality in client records. | `tests/test_bot_handlers.py` name extraction test. |
| CH-006 | Bot UX | `DONE` | Medium | Single-choice steps accepted multi-number input like `1,3`. | Ambiguous/incorrect state transitions. | `tests/test_bot_handlers.py` multi-number rejection tests. |
| CH-007 | Security/Ops | `DONE` | Medium | Calendly webhook signature supported single secret only. | Multi-org signing key rotation difficult. | `tests/test_calendly_webhook_signature.py` with comma-separated secrets. |
| CH-008 | Tests | `DONE` | Low | Reschedule tests used strict tz-aware comparisons against SQLite naive datetimes. | False negatives in CI/local tests. | Re-run webhook reschedule tests after UTC normalization helper. |

## Next Fix Order
1. CH-001: Availability-aware matching (deal-breaker for booking quality).
2. CH-002: Webhook-driven WhatsApp confirmations.
3. Hardening pass: regression tests for end-to-end real Calendly payload variants.

