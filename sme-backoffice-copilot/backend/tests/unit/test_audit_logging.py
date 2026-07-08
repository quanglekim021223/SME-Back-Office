"""Tests for AuditService structured logging.

These tests verify that:
1. AuditService.log() emits records on the ``audit`` logger.
2. All expected fields are present in the emitted record.
3. Sensitive values are never emitted (basic PII guard check).
"""

from __future__ import annotations

import logging
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.services.audit import AuditEvent, AuditService


# ---------------------------------------------------------------------------
# AuditEvent.as_dict()
# ---------------------------------------------------------------------------


class TestAuditEventAsDict:
    """Verify AuditEvent serialises to the correct shape."""

    def test_all_fields_present_when_set(self):
        tenant_id = str(uuid4())
        actor_id = "user-123"
        resource_id = str(uuid4())
        event = AuditEvent(
            event="document.uploaded",
            tenant_id=tenant_id,
            actor_id=actor_id,
            resource_type="document",
            resource_id=resource_id,
            correlation_id="corr-abc",
            extra={"filename": "invoice.pdf"},
        )
        d = event.as_dict()

        assert d["audit_event"] == "document.uploaded"
        assert d["tenant_id"] == tenant_id
        assert d["actor_id"] == actor_id
        assert d["resource_type"] == "document"
        assert d["resource_id"] == resource_id
        assert d["correlation_id"] == "corr-abc"
        assert d["filename"] == "invoice.pdf"
        assert "timestamp" in d

    def test_none_fields_are_omitted(self):
        """Fields that are None must not appear in the dict."""
        event = AuditEvent(event="test.event")
        d = event.as_dict()

        assert "tenant_id" not in d
        assert "actor_id" not in d
        assert "resource_type" not in d
        assert "resource_id" not in d
        assert "correlation_id" not in d

    def test_event_name_is_always_present(self):
        """audit_event key is always in the dict regardless of other fields."""
        event = AuditEvent(event="health.check")
        assert "audit_event" in event.as_dict()

    def test_timestamp_is_iso_format(self):
        """timestamp value is a valid ISO 8601 string."""
        from datetime import datetime

        event = AuditEvent(event="test.event")
        ts = event.as_dict()["timestamp"]
        # Should parse without error
        datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# AuditService.log()
# ---------------------------------------------------------------------------


class TestAuditServiceLog:
    """Verify AuditService emits records via the audit logger."""

    def test_log_emits_on_audit_logger(self):
        service = AuditService()
        event = AuditEvent(event="test.event", tenant_id="t1", actor_id="u1")

        with patch.object(
            logging.getLogger("audit"), "info"
        ) as mock_info:
            service.log(event)

        mock_info.assert_called_once()
        call_args = mock_info.call_args
        # First positional arg is the log message (event name)
        assert call_args[0][0] == "test.event"
        # extra kwarg contains the structured audit dict
        assert "audit" in call_args[1]["extra"]

    def test_log_extra_contains_full_event_dict(self):
        service = AuditService()
        tenant_id = str(uuid4())
        event = AuditEvent(
            event="review_task.approved",
            tenant_id=tenant_id,
            actor_id="user-42",
            resource_type="review_task",
            resource_id=str(uuid4()),
        )

        with patch.object(logging.getLogger("audit"), "info") as mock_info:
            service.log(event)

        extra = mock_info.call_args[1]["extra"]["audit"]
        assert extra["audit_event"] == "review_task.approved"
        assert extra["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# AuditService convenience methods
# ---------------------------------------------------------------------------


class TestAuditServiceConvenienceMethods:
    """Convenience factory methods emit the correct event names and fields."""

    def test_log_document_uploaded_event_name(self):
        service = AuditService()
        tenant_id = uuid4()
        doc_id = uuid4()

        with patch.object(logging.getLogger("audit"), "info") as mock_info:
            service.log_document_uploaded(
                tenant_id=tenant_id,
                actor_id="user-1",
                document_id=doc_id,
                filename="invoice.pdf",
                correlation_id="corr-xyz",
            )

        extra = mock_info.call_args[1]["extra"]["audit"]
        assert extra["audit_event"] == "document.uploaded"
        assert extra["tenant_id"] == str(tenant_id)
        assert extra["resource_id"] == str(doc_id)
        assert extra["filename"] == "invoice.pdf"
        assert extra["correlation_id"] == "corr-xyz"

    def test_log_review_action_approve(self):
        service = AuditService()
        tenant_id = uuid4()
        task_id = uuid4()

        with patch.object(logging.getLogger("audit"), "info") as mock_info:
            service.log_review_action(
                event="review_task.approved",
                tenant_id=tenant_id,
                actor_id="user-99",
                review_task_id=task_id,
                action="approve",
                correlation_id=None,
            )

        extra = mock_info.call_args[1]["extra"]["audit"]
        assert extra["audit_event"] == "review_task.approved"
        assert extra["action"] == "approve"
        assert extra["resource_type"] == "review_task"
        assert extra["resource_id"] == str(task_id)

    def test_log_review_action_corrected(self):
        service = AuditService()

        with patch.object(logging.getLogger("audit"), "info") as mock_info:
            service.log_review_action(
                event="review_task.corrected",
                tenant_id=uuid4(),
                actor_id="user-5",
                review_task_id=uuid4(),
                action="correct-classification",
            )

        extra = mock_info.call_args[1]["extra"]["audit"]
        assert extra["audit_event"] == "review_task.corrected"
        assert extra["action"] == "correct-classification"


# ---------------------------------------------------------------------------
# PII / sensitive data guard
# ---------------------------------------------------------------------------


class TestAuditLogPIIGuard:
    """Verify sensitive data patterns are not present in audit log output."""

    def test_audit_dict_does_not_contain_raw_financial_data(self):
        """Extra fields should never carry extracted invoice amounts or raw OCR."""
        service = AuditService()
        event = AuditEvent(
            event="document.uploaded",
            tenant_id=str(uuid4()),
            extra={"filename": "invoice.pdf"},  # only safe metadata
        )
        d = event.as_dict()

        # Ensure no suspicious keys leak financial/PII data
        forbidden_keys = {
            "total_amount", "subtotal", "tax", "vendor_address",
            "raw_text", "ocr_output", "bank_account",
        }
        for key in forbidden_keys:
            assert key not in d, f"Sensitive key '{key}' found in audit dict"


class TestRedactingLoggingFilter:
    """Verify RedactingLoggingFilter successfully redacts PII and financial fields."""

    def test_redacts_sensitive_keys_in_dict_args(self):
        from app.observability.logging_filter import RedactingLoggingFilter

        log_filter = RedactingLoggingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Raw event info",
            args=({"customer_name": "John Doe", "amount": 100.0, "safe_key": "safe"},),
            exc_info=None,
        )

        assert log_filter.filter(record)
        arg_dict = record.args
        assert isinstance(arg_dict, dict)
        assert arg_dict.get("customer_name") == "[REDACTED]"
        assert arg_dict.get("amount") == "[REDACTED]"
        assert arg_dict.get("safe_key") == "safe"

    def test_redacts_emails_in_messages(self):
        from app.observability.logging_filter import RedactingLoggingFilter

        log_filter = RedactingLoggingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="User email was test@example.com",
            args=(),
            exc_info=None,
        )

        assert log_filter.filter(record)
        assert record.msg == "User email was [EMAIL_REDACTED]"

