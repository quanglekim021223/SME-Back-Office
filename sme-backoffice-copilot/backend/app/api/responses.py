"""Shared API response and error conventions."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    """Machine-readable API error payload."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable error summary.")
    details: Any | None = Field(
        default=None,
        description="Optional structured details for debugging or validation.",
    )


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorPayload
    correlation_id: str


class APIError(Exception):
    """Application-level API error with stable response shape."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)
