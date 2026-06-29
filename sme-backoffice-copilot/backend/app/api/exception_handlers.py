"""FastAPI exception handlers using the standard API error envelope."""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from app.api.responses import APIError, ErrorPayload, ErrorResponse
from app.core.middleware import CORRELATION_ID_HEADER


def get_correlation_id(request: Request) -> str:
    """Return the request correlation ID set by middleware, if available."""

    correlation_id = getattr(request.state, "correlation_id", None)
    if isinstance(correlation_id, str):
        return correlation_id
    return "unknown"


def error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    """Build a JSONResponse with the standard API error envelope."""

    correlation_id = get_correlation_id(request)
    payload = ErrorResponse(
        error=ErrorPayload(code=code, message=message, details=details),
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers={CORRELATION_ID_HEADER: correlation_id},
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle explicit application API errors."""

    assert isinstance(exc, APIError)
    return error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Normalize FastAPI HTTPException responses."""

    assert isinstance(exc, HTTPException)
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    details = None if isinstance(exc.detail, str) else exc.detail
    return error_response(
        request=request,
        status_code=exc.status_code,
        code="http_error",
        message=message,
        details=details,
    )


async def validation_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Normalize request validation errors."""

    assert isinstance(exc, RequestValidationError)
    return error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        message="Request validation failed.",
        details=exc.errors(),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return a safe response for unexpected errors."""

    return error_response(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_server_error",
        message="Unexpected server error.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register API error handlers on the FastAPI app."""

    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
