# Physio Booking System V1 — Matching & Availability Spec
Version: 1.0  
Date: 2026-02-04  
Status: Locked for V1 build

This spec defines the therapist matching logic and availability caching rules for V1. It implements the
decision rules confirmed by the product owner and aligns with the V1 developer document.

---

## 1) Goals
- Deterministic matching for the WhatsApp booking bot.
- Calendly remains the source of truth for slot availability.
- Explainable therapist selection with one-line rationale.
- Lightweight and auditable (store the decision factors and alternatives).

---

## 2) Inputs Collected by the Bot
- **Session duration**: 30 / 45 / 60 minutes
- **Preferred time band**: one of the configured time bands (see §4)
- **Specialty**: selected from the union of therapist specialties
- **Preferred days**: derived from the union of available days across therapists

---

## 3) Matching Priority and Scoring

### 3.1 Priority Rules (High → Low)
1) **Specialty match (primary)**  
   - If possible, select from therapists who match the requested specialty.
2) **Continuity bonus**  
   - If the client has a previous therapist, that therapist receives a bonus.
3) **Time-band match**  
   - Therapist has availability in the requested day/time band.
4) **Lower load (tie-breaker)**  
   - Fewer upcoming sessions in the next 7 days wins.

### 3.2 Fallback Order (if no match)
1) **Ignore time preference**, keep specialty  
2) **Ignore specialty**, keep time preference  
3) **Any therapist** (lowest load)

### 3.3 Rationale (one-line)
Format:
```
Matched <specialty> specialist Dr. XYZ, <Day> <Band>. Use booking link to book a slot: <link>
```

---

## 4) Time Bands (V1 Default)
These are configurable but default to:
- **Band 1**: 08:00–11:00
- **Band 2**: 11:00–16:00
- **Band 3**: 16:00–20:00

---

## 5) Availability Caching (Daily Job)
Purpose: fast matching without computing availability outside Calendly.

### 5.1 What to Cache
For each **therapist + duration + date + time band**, store:
- `has_slots` (boolean)
- optional `next_slot_time` (timestamp)

### 5.2 Cache Window
- **Next 14 days** (rolling)
- Run **daily** (or more often if required later)

### 5.3 Failure Behavior
- If cache is stale, fallback to live Calendly availability queries.
- Calendly still decides actual slot booking; cache only guides the match.

---

## 6) Load Calculation
Load = **number of upcoming sessions in next 7 days** per therapist.

---

## 7) Auditing Requirements
For each matching decision, persist:
- input parameters (duration, time band, preferred days, specialty)
- selected therapist
- scoring breakdown per therapist
- rationale
- rejected alternatives (for traceability)

This enables admin review and debugging without manual reconstruction.

---

## 8) Notes
- WhatsApp bot handles **booking only** (no payments).
- Admin/therapist finance workflows stay in WebUI.
- Calendly remains authoritative for booking, reschedule, cancel.
