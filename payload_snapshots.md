# Payload Snapshots for UAT

## `GET /api/v1/admin/billing/queue?quick_range=7d`
```json
{
  "items": [
    {
      "session_id": 1,
      "client_id": 1,
      "client_name": "Patient Alpha",
      "therapist_id": 1,
      "therapist_name": "Dr. Jane Payload",
      "start_time": "2026-02-21T22:28:39.166427-08:00",
      "end_time": "2026-02-21T23:13:39.166427-08:00",
      "duration_minutes": 45,
      "status": "completed",
      "currency": "HKD",
      "expected_charge_cents": 120000,
      "paid_cents": 60000,
      "receipted_cents": 0,
      "outstanding_cents": 60000,
      "needs_confirmation": true,
      "default_receipt_amount_cents": 100000,
      "last_payment_at": "2026-02-22T12:28:39.166427-08:00",
      "last_receipt_at": null
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

## `GET /api/v1/admin/invoice-presets`
```json
[
  {
    "id": 2,
    "type": "special_note",
    "label": "Rest Note",
    "value": "Recommended 2 days of shoulder rest.",
    "is_active": true,
    "sort_order": 1,
    "updated_at": "2026-02-23T06:28:39.169071"
  },
  {
    "id": 1,
    "type": "diagnosis",
    "label": "Shoulder Impingement",
    "value": "Subacromial shoulder impingement",
    "is_active": true,
    "sort_order": 1,
    "updated_at": "2026-02-23T06:28:39.168957"
  }
]
```

## `GET /api/v1/admin/clients/1/payments?source=admin_manual`
```json
[
  {
    "id": 2,
    "client_id": 1,
    "source": "admin_manual",
    "session_id": null,
    "amount_cents": 50000,
    "currency": "HKD",
    "method": "cash",
    "status": "confirmed",
    "received_by_role": "admin",
    "received_by_name": null,
    "paid_at": "2026-02-22T20:28:39.166427-08:00",
    "reference": null,
    "notes": null,
    "recorded_by_user_id": 1,
    "updated_at": "2026-02-22T22:28:39.168820-08:00",
    "created_at": "2026-02-22T22:28:39.168783-08:00"
  }
]
```
