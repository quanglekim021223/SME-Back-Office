"""Application middleware registration."""

from collections.abc import Awaitable, Callable
from typing import cast
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings

CORRELATION_ID_HEADER = "X-Correlation-ID"

CallNext = Callable[[Request], Awaitable[Response]]


async def correlation_id_middleware(
    request: Request,
    call_next: CallNext,
) -> Response:
    """Attach a correlation ID to request state and response headers."""

    correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid4())
    request.state.correlation_id = correlation_id

    response = await call_next(request)
    response.headers[CORRELATION_ID_HEADER] = correlation_id
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
