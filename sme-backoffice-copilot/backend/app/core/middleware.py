"""Application middleware registration."""

import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"
logger = logging.getLogger("app.http")

CallNext = Callable[[Request], Awaitable[Response]]


async def correlation_id_middleware(
    request: Request,
    call_next: CallNext,
) -> Response:
    """Attach a correlation ID to request state and response headers."""

    started_at = perf_counter()
    correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid4())
    request_id = request.headers.get(REQUEST_ID_HEADER) or correlation_id
    request.state.correlation_id = correlation_id
    request.state.request_id = request_id

    response = await call_next(request)
    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    response.headers[CORRELATION_ID_HEADER] = correlation_id
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info(
        "http.request.completed",
        extra={
            "event": "http.request.completed",
            "request_id": request_id,
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


def register_middleware(app: FastAPI) -> None:
    """Register application middleware in one place."""

    settings = cast(Settings, app.state.settings)
    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_headers=["*"],
        allow_methods=["*"],
        allow_origins=settings.cors_origins,
    )
    app.middleware("http")(correlation_id_middleware)
