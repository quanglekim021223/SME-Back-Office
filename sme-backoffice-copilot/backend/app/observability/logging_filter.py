"""Redacting logging filter to ensure PII and sensitive data never leaks into logs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

# Sensitive keys patterns that must have their values replaced with [REDACTED]
SENSITIVE_PATTERNS = [
    r"(?i)(customer|supplier|vendor|party)_?(name|address|tax_id|phone|email)",
    r"(?i)email|phone|account|iban|subtotal|tax|total_amount|amount|balance",
    r"(?i)ocr_text|raw_text|full_text|payload|prompt|assembled_invoice|structured_output",
]


class RedactingLoggingFilter(logging.Filter):
    """Logging filter that redacts sensitive values from log records.

    It scans log record arguments, dictionary attributes, and log messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Redact values in extra dicts (like record.args or custom extra kwargs)
        if isinstance(record.args, dict):
            record.args = self._redact_dict(record.args)
        elif record.args:
            # If args is a tuple, convert to list, redact, then back to tuple
            new_args: list[Any] = []
            for arg in record.args:
                if isinstance(arg, dict):
                    new_args.append(self._redact_dict(arg))
                elif isinstance(arg, str):
                    new_args.append(self._redact_string(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        # 2. Check all custom attributes attached as 'extra' to the record
        # Standard LogRecord attributes are fixed, so we only modify user-supplied ones
        # which are typically passed via extra={...}
        for key, val in list(record.__dict__.items()):
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            }:
                if isinstance(val, dict):
                    record.__dict__[key] = self._redact_dict(val)
                elif isinstance(val, str):
                    record.__dict__[key] = self._redact_string(val)

        # 3. Also redact from the main message if it is a string
        if isinstance(record.msg, str):
            record.msg = self._redact_string(record.msg)

        return True

    def _redact_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact dictionary keys that suggest sensitive content."""
        redacted: dict[str, Any] = {}
        for k, v in d.items():
            normalized_key = k.lower()
            # If the key name matches any of our sensitive patterns, redact it
            if any(
                re.search(pattern, normalized_key) for pattern in SENSITIVE_PATTERNS
            ):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, dict):
                redacted[k] = self._redact_dict(v)
            elif isinstance(v, list):
                redacted[k] = [
                    self._redact_dict(item) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                redacted[k] = v
        return redacted

    def _redact_string(self, s: str) -> str:
        """Scan string for raw sensitive emails or simple patterns to redact."""
        # Simple email regex redaction
        email_pattern = r"[\w\.-]+@[\w\.-]+\.\w+"
        s = re.sub(email_pattern, "[EMAIL_REDACTED]", s)
        return s


class StructuredLogFormatter(logging.Formatter):
    """Format log records as compact JSON with safe operational fields."""

    RESERVED_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self.RESERVED_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


class HumanReadableLogFormatter(logging.Formatter):
    """Format structured log records for local terminal readability."""

    RESERVED_ATTRS = StructuredLogFormatter.RESERVED_ATTRS

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            self.formatTime(record, "%H:%M:%S"),
            record.levelname,
            record.name,
            record.getMessage(),
        ]
        for key, value in record.__dict__.items():
            if key in self.RESERVED_ATTRS or key.startswith("_"):
                continue
            if key in {"event"}:
                continue
            parts.append(f"{key}={value}")
        if record.exc_info:
            parts.append(self.formatException(record.exc_info))
        return " ".join(str(part) for part in parts)


def setup_logging_redaction() -> None:
    """Register the RedactingLoggingFilter on all active log handlers."""

    redact_filter = RedactingLoggingFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(redact_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redact_filter)

    # Also explicitly add to other loggers to ensure they are filtered
    for logger_name in [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "app",
        "app.http",
        "app.workflow",
        "audit",
    ]:
        logger = logging.getLogger(logger_name)
        logger.addFilter(redact_filter)
        for handler in logger.handlers:
            handler.addFilter(redact_filter)


def setup_structured_logging(*, log_format: str = "pretty") -> None:
    """Apply an application formatter to currently configured log handlers."""

    formatter: logging.Formatter
    if log_format == "json":
        formatter = StructuredLogFormatter()
    else:
        formatter = HumanReadableLogFormatter()
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    handlers = root_logger.handlers or [logging.StreamHandler()]
    if not root_logger.handlers:
        root_logger.addHandler(handlers[0])
    for handler in handlers:
        handler.setFormatter(formatter)
    for logger_name in ["app", "app.http", "app.workflow", "audit"]:
        logging.getLogger(logger_name).setLevel(logging.INFO)
