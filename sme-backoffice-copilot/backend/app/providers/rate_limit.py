"""Distributed worker-side provider rate limiting."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from ssl import CERT_REQUIRED
from time import monotonic, time
from typing import Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis.asyncio import Redis

from app.providers.errors import ProviderExecutionError


class ProviderRateLimiter(Protocol):
    """Boundary applied before every OCR or LLM provider attempt."""

    async def acquire(self, *, provider_name: str, route_kind: str) -> None:
        """Wait until one provider request token is available."""

    async def aclose(self) -> None:
        """Release limiter resources."""


class NoopProviderRateLimiter:
    """Limiter used when distributed throttling is disabled."""

    async def acquire(self, *, provider_name: str, route_kind: str) -> None:
        del provider_name, route_kind

    async def aclose(self) -> None:
        return None


class RedisFixedWindowProviderRateLimiter:
    """Enforce provider request-per-second budgets across worker processes."""

    _INCREMENT_SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
      redis.call('PEXPIRE', KEYS[1], ARGV[1])
    end
    return current
    """

    def __init__(
        self,
        *,
        redis_client: Redis,
        ocr_requests_per_second: int,
        llm_requests_per_second: int,
        wait_timeout_seconds: float,
    ) -> None:
        self.redis_client = redis_client
        self.ocr_requests_per_second = ocr_requests_per_second
        self.llm_requests_per_second = llm_requests_per_second
        self.wait_timeout_seconds = wait_timeout_seconds

    @classmethod
    def from_url(
        cls,
        *,
        redis_url: str,
        ocr_requests_per_second: int,
        llm_requests_per_second: int,
        wait_timeout_seconds: float,
    ) -> RedisFixedWindowProviderRateLimiter:
        # ``redis.asyncio`` accepts ``required`` in a URL but not Celery's
        # ``CERT_REQUIRED`` spelling. Remove a URL-provided setting so the
        # explicit stdlib value below is the single TLS source of truth.
        parsed_url = urlsplit(redis_url)
        sanitized_query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
                if key != "ssl_cert_reqs"
            ]
        )
        sanitized_redis_url = urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                sanitized_query,
                parsed_url.fragment,
            )
        )
        return cls(
            # Upstash exposes TLS-only Redis endpoints.  Pass the stdlib SSL
            # constant explicitly so this async client does not depend on the
            # URL query-string spelling accepted by Celery/Kombu.
            redis_client=Redis.from_url(
                sanitized_redis_url,
                decode_responses=True,
                ssl_cert_reqs=CERT_REQUIRED,
            ),
            ocr_requests_per_second=ocr_requests_per_second,
            llm_requests_per_second=llm_requests_per_second,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    async def acquire(self, *, provider_name: str, route_kind: str) -> None:
        limit = (
            self.llm_requests_per_second
            if route_kind == "llm"
            else self.ocr_requests_per_second
        )
        deadline = monotonic() + self.wait_timeout_seconds
        while True:
            now_ms = int(time() * 1000)
            window = now_ms // 1000
            key = f"provider-rate:{route_kind}:{provider_name}:{window}"
            count = await cast(
                Awaitable[object],
                self.redis_client.eval(
                    self._INCREMENT_SCRIPT,
                    1,
                    key,
                    "1500",
                ),
            )
            if isinstance(count, int) and count <= limit:
                return

            wait_seconds = max(((window + 1) * 1000 - now_ms) / 1000, 0.01)
            if monotonic() + wait_seconds > deadline:
                raise ProviderExecutionError(
                    f"Provider rate-limit wait timed out for {provider_name}."
                )
            await asyncio.sleep(wait_seconds)

    async def aclose(self) -> None:
        await self.redis_client.aclose()
