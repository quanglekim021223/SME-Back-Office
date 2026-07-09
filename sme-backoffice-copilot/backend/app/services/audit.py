"""Structured audit logging service.

This module emits audit events as structured JSON log records via the standard
Python :mod:`logging` facility.  Events are distinct from application debug
logs — they document **who** did **what** to **which resource** and **when**,
forming the foundation for compliance and forensics tooling.

Design notes
------------
* We intentionally avoid a separate database table for MVP audit events that
  originate outside the review-task flow (e.g. document uploads, list reads).
  The ``ReviewTaskDecisionService`` already persists ``AuditEvent`` model
  objects; this service covers the remaining access patterns with log-based
  events that can be shipped to a SIEM / log aggregator later.
* All fields use ``str`` types so the log record is safe to serialize to JSON
  by any structured logging handler (e.g. ``python-json-logger``).
* Sensitive values (e.g. raw file content, extracted financial data) must
  **never** be passed to this service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

_audit_logger = logging.getLogger("audit")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Structured audit event emitted as a log record.

    All fields are optional-safe so callers can pass only what they know.
    """

    event: str
    tenant_id: str | None = None
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    correlation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds")
    )

    def as_dict(self) -> dict[str, Any]:
        """Return a flat dict suitable for structured log emission."""
        payload: dict[str, Any] = {
            "audit_event": self.event,
            "tenant_id": self.tenant_id,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }
        payload.update(self.extra)
        return {k: v for k, v in payload.items() if v is not None}


class AuditService:
    """Emit structured audit events via the ``audit`` logger.

    Usage::

        service = AuditService()
        service.log(AuditEvent(
            event="document.uploaded",
            tenant_id=str(tenant_id),
            actor_id=principal.user_id,
            resource_type="document",
            resource_id=str(document_id),
            correlation_id=correlation_id,
        ))

    Convenience factory methods are provided for common events so that
    call-sites remain concise and the event name vocabulary stays consistent.
    """

    def log(self, event: AuditEvent) -> None:
        """Emit *event* as a structured INFO log record.

        The logger name is ``audit``; configure a separate handler for it in
        production to route events to a dedicated audit sink.
        """
        _audit_logger.info(event.event, extra={"audit": event.as_dict()})

    # ------------------------------------------------------------------
    # Convenience factories
    # ------------------------------------------------------------------

    def log_document_uploaded(
        self,
        *,
        tenant_id: UUID | str,
        actor_id: str | None,
        document_id: UUID | str,
        filename: str,
        correlation_id: str | None = None,
    ) -> None:
        """Emit a ``document.uploaded`` audit event."""
        self.log(
            AuditEvent(
                event="document.uploaded",
                tenant_id=str(tenant_id),
                actor_id=actor_id,
                resource_type="document",
                resource_id=str(document_id),
                correlation_id=correlation_id,
                extra={"filename": filename},
            )
        )

    def log_review_action(
        self,
        *,
        event: str,
        tenant_id: UUID | str,
        actor_id: str | None,
        review_task_id: UUID | str,
        action: str,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit a review-task action audit event (approve / reject / correct)."""
        self.log(
            AuditEvent(
                event=event,
                tenant_id=str(tenant_id),
                actor_id=actor_id,
                resource_type="review_task",
                resource_id=str(review_task_id),
                correlation_id=correlation_id,
                extra={"action": action, **(extra or {})},
            )
        )
