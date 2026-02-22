# Backend Bind Sheet - Phase D Reports Checkpoint (2026-02-22 19:20 HKT)

Phase D backend reporting endpoints are implemented and ready for FE bind.

- OpenAPI snapshot: `docs/contracts/openapi-v1-2026-02-22-phaseD-reports-checkpoint.json`
- Status: implemented + tested

## 1) Therapist Utilization Report

`GET /api/v1/admin/reports/therapist-utilization`

### Query Params

- `from` (required, ISO datetime)
- `to` (required, ISO datetime)
- `therapist_id` (optional, int)
- `limit` (optional, default `50`, max `200`)
- `offset` (optional, default `0`)

### 200 Response

```json
{
  "items": [
    {
      "therapist_id": 5,
      "therapist_name": "Dr. Avishek Majumder",
      "completed_sessions": 8,
      "scheduled_sessions": 3,
      "cancelled_sessions": 1,
      "no_show_sessions": 0,
      "utilized_minutes": 375,
      "period_start": "2026-02-01T00:00:00+00:00",
      "period_end": "2026-02-22T00:00:00+00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

Notes:
- `utilized_minutes` includes sessions with status `started` and `completed`.

## 2) Therapist Payroll Summary

`GET /api/v1/admin/reports/therapist-payroll`

### Query Params

- `from` (required, ISO datetime)
- `to` (required, ISO datetime)
- `therapist_id` (optional, int)
- `limit` (optional, default `50`, max `200`)
- `offset` (optional, default `0`)

### 200 Response

```json
{
  "items": [
    {
      "therapist_id": 5,
      "therapist_name": "Dr. Avishek Majumder",
      "completed_sessions": 8,
      "payable_minutes": 360,
      "estimated_payable_cents": 780000,
      "currency": "HKD",
      "period_start": "2026-02-01T00:00:00+00:00",
      "period_end": "2026-02-22T00:00:00+00:00"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

Notes:
- Completed sessions only are included in payroll aggregates.
- `estimated_payable_cents` resolution order per completed session:
  1. `session.charge_amount_cents`
  2. active client-plan assigned `billing_plan.amount_cents` for matching duration
  3. `0`

## Error Handling

- Invalid date range (`from >= to`) returns `400`.

