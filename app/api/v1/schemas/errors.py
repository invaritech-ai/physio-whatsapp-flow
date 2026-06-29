"""Standardized error response schemas for API consistency."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """Structured error detail for API responses."""

    code: str
    message: str
    field: str | None = None
    docs_url: str | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """Standardized error response envelope."""

    error: ErrorDetail
    request_id: str
    timestamp: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "client_not_found",
                    "message": "The specified client does not exist",
                    "field": "client_id",
                    "docs_url": None,
                    "details": {"client_id": 999},
                },
                "request_id": "req_abc123",
                "timestamp": "2026-02-23T22:00:00Z",
            }
        }
    )


ERROR_CODES: dict[str, dict[str, Any]] = {
    "client_not_found": {
        "message": "The specified client does not exist",
        "status_code": 404,
    },
    "client_phone_already_exists": {
        "message": "A client with this phone number already exists",
        "status_code": 400,
    },
    "session_not_found": {
        "message": "The specified session does not exist",
        "status_code": 404,
    },
    "therapist_not_found": {
        "message": "The specified therapist does not exist",
        "status_code": 404,
    },
    "invoice_not_found": {
        "message": "The specified invoice does not exist",
        "status_code": 404,
    },
    "invoice_preset_not_found": {
        "message": "The specified invoice preset does not exist",
        "status_code": 404,
    },
    "user_not_found": {
        "message": "The specified user does not exist",
        "status_code": 404,
    },
    "invalid_session_for_client": {
        "message": "The session does not belong to the specified client",
        "status_code": 400,
    },
    "therapist_session_mismatch": {
        "message": "The therapist is not associated with the specified session",
        "status_code": 400,
    },
    "payment_source_requires_session_id": {
        "message": "Payments with source 'session_linked' require a session_id",
        "status_code": 400,
    },
    "admin_manual_requires_null_session_id": {
        "message": "Payments with source 'admin_manual' must not have a session_id",
        "status_code": 400,
    },
    "invalid_diagnosis_preset_id": {
        "message": "The diagnosis preset is invalid, inactive, or not found",
        "status_code": 400,
    },
    "invalid_special_note_preset_id": {
        "message": "The special note preset is invalid, inactive, or not found",
        "status_code": 400,
    },
    "invalid_service_type": {
        "message": "Service type must be one of: standard, supervised_physio, other",
        "status_code": 400,
    },
    "manual_session_start_at_required": {
        "message": "Session date/time is required when generating a receipt without selecting a session",
        "status_code": 400,
    },
    "manual_session_start_at_conflicts_with_session": {
        "message": "Session date/time cannot be provided when a session is selected",
        "status_code": 400,
    },
    "amount_cents_required": {
        "message": "Amount is required when no default charge is available",
        "status_code": 400,
    },
    "amount_exceeds_available_to_receipt": {
        "message": "Receipt amount exceeds available balance",
        "status_code": 400,
    },
    "no_changes_requested": {
        "message": "No changes were provided in the update request",
        "status_code": 400,
    },
    "invoice_generation_conflict": {
        "message": "A conflict occurred during invoice generation",
        "status_code": 409,
    },
    "payment_record_conflict": {
        "message": "A conflict occurred while recording the payment",
        "status_code": 409,
    },
    "access_denied": {
        "message": "You do not have permission to perform this action",
        "status_code": 403,
    },
    "validation_error": {
        "message": "The request contains invalid data",
        "status_code": 422,
    },
    "rate_limit_exceeded": {
        "message": "Too many requests. Please try again later.",
        "status_code": 429,
    },
    "internal_error": {
        "message": "An unexpected error occurred",
        "status_code": 500,
    },
}
