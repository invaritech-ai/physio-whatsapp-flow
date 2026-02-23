"""Centralized exception hierarchy for consistent error handling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.api.v1.schemas.errors import ERROR_CODES, ErrorDetail, ErrorResponse


class AppException(Exception):
    """
    Base application exception with structured error details.
    
    All business logic exceptions should inherit from this class
    to ensure consistent error responses across the API.
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.field = field
        self.details = details or {}

        error_meta = ERROR_CODES.get(code, {})
        self.message = message or error_meta.get("message", "An error occurred")
        self.status_code = status_code or error_meta.get("status_code", 500)

        super().__init__(self.message)

    def to_error_detail(self) -> ErrorDetail:
        return ErrorDetail(
            code=self.code,
            message=self.message,
            field=self.field,
            details=self.details if self.details else None,
        )

    def to_error_response(self, request_id: str) -> ErrorResponse:
        return ErrorResponse(
            error=self.to_error_detail(),
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
        )

    def to_http_exception(self, request_id: str = "unknown") -> HTTPException:
        response = self.to_error_response(request_id)
        return HTTPException(
            status_code=self.status_code,
            detail=response.model_dump(mode="json"),
        )


class NotFoundError(AppException):
    """Resource not found exception."""

    def __init__(
        self,
        code: str = "not_found",
        message: str | None = None,
        resource_type: str | None = None,
        resource_id: int | str | None = None,
    ) -> None:
        details = {}
        if resource_type:
            details["resource_type"] = resource_type
        if resource_id is not None:
            details["resource_id"] = resource_id

        super().__init__(code=code, message=message, details=details, status_code=404)


class ValidationError(AppException):
    """Validation error exception."""

    def __init__(
        self,
        code: str = "validation_error",
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, field=field, details=details, status_code=422)


class BusinessLogicError(AppException):
    """Business logic constraint violation."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, field=field, details=details, status_code=400)


class ConflictError(AppException):
    """Conflict error (e.g., duplicate, race condition)."""

    def __init__(
        self,
        code: str = "conflict",
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, details=details, status_code=409)


class AuthorizationError(AppException):
    """Authorization/permission error."""

    def __init__(
        self,
        code: str = "access_denied",
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, details=details, status_code=403)


class RateLimitError(AppException):
    """Rate limit exceeded error."""

    def __init__(
        self,
        retry_after: int | None = None,
    ) -> None:
        details = {}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__(code="rate_limit_exceeded", details=details, status_code=429)


def raise_not_found(
    code: str,
    resource_type: str | None = None,
    resource_id: int | str | None = None,
) -> None:
    """Convenience function to raise NotFoundError."""
    raise NotFoundError(code=code, resource_type=resource_type, resource_id=resource_id)


def raise_validation(
    code: str,
    message: str | None = None,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Convenience function to raise ValidationError."""
    raise ValidationError(code=code, message=message, field=field, details=details)


def raise_business(
    code: str,
    message: str | None = None,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Convenience function to raise BusinessLogicError."""
    raise BusinessLogicError(code=code, message=message, field=field, details=details)
