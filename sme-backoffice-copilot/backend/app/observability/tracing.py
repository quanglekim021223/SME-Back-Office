"""Small provider-neutral tracing boundary with safe payload redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.core.config import Settings, TracingBackendType

logger = logging.getLogger(__name__)

SENSITIVE_TRACE_KEYS = {
    "address",
    "assembled_invoice",
    "content",
    "customer_address",
    "customer_name",
    "customer_tax_id",
    "email",
    "full_text",
    "input",
    "line_item",
    "message",
    "messages",
    "metadata",
    "ocr_text",
    "ocr_text_preview",
    "output",
    "party",
    "payload",
    "phone",
    "prompt",
    "raw",
    "raw_text",
    "structured_output",
    "supplier_address",
    "supplier_name",
    "supplier_tax_id",
    "tax_id",
}

SENSITIVE_KEY_PARTS = (
    "account",
    "address",
    "email",
    "iban",
    "phone",
    "raw_",
    "routing",
    "tax_id",
)


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One redacted trace event emitted by workflow/provider code."""

    name: str
    payload: Mapping[str, object] = field(default_factory=dict)
    correlation_id: str | None = None
    emitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class TraceProvider(Protocol):
    """Minimal tracing interface compatible with Langfuse/LangSmith adapters."""

    def record_event(
        self,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Record one trace event."""


class NoOpTraceProvider:
    """Tracing provider used when tracing is disabled."""

    def record_event(
        self,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Drop the trace event."""

        del name, payload, correlation_id


class InMemoryTraceProvider:
    """Test/debug trace sink that keeps emitted events in process memory."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record_event(
        self,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Append one event."""

        self.events.append(
            TraceEvent(
                name=name,
                payload=dict(payload or {}),
                correlation_id=correlation_id,
            )
        )


class LoggingTraceProvider:
    """Local placeholder for external Langfuse/LangSmith exporters.

    It preserves the same app-facing interface while we avoid adding vendor SDK
    dependencies until a real backend is selected and enabled.
    """

    def __init__(
        self,
        *,
        backend: TracingBackendType,
        project_name: str,
    ) -> None:
        self.backend = backend
        self.project_name = project_name

    def record_event(
        self,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Emit one redacted event to structured logs for local inspection."""

        logger.info(
            "trace_event",
            extra={
                "trace_backend": self.backend.value,
                "trace_project": self.project_name,
                "trace_name": name,
                "trace_correlation_id": correlation_id,
                "trace_payload": dict(payload or {}),
            },
        )


class RedactingTraceProvider:
    """Wrapper that redacts/minimizes every payload before export."""

    def __init__(
        self,
        wrapped: TraceProvider,
        *,
        max_payload_chars: int,
    ) -> None:
        self.wrapped = wrapped
        self.max_payload_chars = max_payload_chars

    def record_event(
        self,
        name: str,
        payload: Mapping[str, object] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Record a redacted event."""

        self.wrapped.record_event(
            name,
            minimize_trace_payload(
                payload or {},
                max_payload_chars=self.max_payload_chars,
            ),
            correlation_id=correlation_id,
        )


def build_trace_provider_from_settings(settings: Settings) -> TraceProvider:
    """Build the configured trace provider.

    External SDK exporters are intentionally not pulled in yet; Langfuse and
    LangSmith config currently route to safe structured logging behind the same
    interface.
    """

    if settings.tracing_backend == TracingBackendType.DISABLED:
        return NoOpTraceProvider()

    provider: TraceProvider = LoggingTraceProvider(
        backend=settings.tracing_backend,
        project_name=(
            settings.langsmith_project
            if settings.tracing_backend == TracingBackendType.LANGSMITH
            else settings.tracing_project_name
        ),
    )
    if settings.tracing_redaction_enabled:
        return RedactingTraceProvider(
            provider,
            max_payload_chars=settings.tracing_max_payload_chars,
        )
    return provider


def record_trace_event(
    trace_provider: object | None,
    name: str,
    payload: Mapping[str, object] | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Best-effort trace helper; tracing must never break workflow execution."""

    if trace_provider is None or not isinstance(trace_provider, TraceProvider):
        return
    try:
        trace_provider.record_event(
            name,
            payload,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception("Failed to record trace event %s.", name)


def minimize_trace_payload(
    payload: Mapping[str, object],
    *,
    max_payload_chars: int,
) -> dict[str, object]:
    """Redact sensitive fields and cap payload size before export."""

    redacted = {
        key: redact_trace_value(key=key, value=value)
        for key, value in payload.items()
    }
    encoded = json.dumps(redacted, default=str, sort_keys=True)
    if len(encoded) <= max_payload_chars:
        return redacted
    return {
        "_truncated": True,
        "payload_chars": len(encoded),
        "payload_preview": encoded[:max_payload_chars],
    }


def redact_trace_value(*, key: str, value: object) -> object:
    """Recursively redact values whose key suggests financial/customer content."""

    normalized_key = key.lower()
    if normalized_key in SENSITIVE_TRACE_KEYS or any(
        part in normalized_key for part in SENSITIVE_KEY_PARTS
    ):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_trace_value(
                key=str(child_key),
                value=child_value,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [
            redact_trace_value(key=key, value=item)
            for item in value[:20]
        ]
    if isinstance(value, tuple):
        return tuple(redact_trace_value(key=key, value=item) for item in value[:20])
    if isinstance(value, str) and len(value) > 256:
        return f"{value[:256]}…"
    return value
