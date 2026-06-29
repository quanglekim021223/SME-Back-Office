"""Application middleware registration."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

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

    app.middleware("http")(correlation_id_middleware)
