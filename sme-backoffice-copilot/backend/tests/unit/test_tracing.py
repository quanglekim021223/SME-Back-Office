"""Tests proving that sensitive financial fields are always redacted from trace payloads.

Covers:
- Every key in SENSITIVE_TRACE_KEYS is redacted.
- Every SENSITIVE_KEY_PARTS substring match is redacted (e.g. supplier_account_number).
- Safe/non-sensitive keys pass through unchanged.
- Nested dict values are recursively redacted.
- List values are recursively redacted (capped at 20 items).
- Long string values are truncated (> 256 chars).
- Oversized payloads are replaced with a truncation sentinel.
- NoOpTraceProvider drops events silently.
- InMemoryTraceProvider records events in order.
- record_trace_event helper is a no-op when provider is None or wrong type.
"""

from __future__ import annotations

from app.observability.tracing import (
    SENSITIVE_KEY_PARTS,
    SENSITIVE_TRACE_KEYS,
    InMemoryTraceProvider,
    NoOpTraceProvider,
    RedactingTraceProvider,
    minimize_trace_payload,
    record_trace_event,
    redact_trace_value,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_redacting(max_chars: int = 4000) -> tuple[InMemoryTraceProvider, RedactingTraceProvider]:
    sink = InMemoryTraceProvider()
    return sink, RedactingTraceProvider(sink, max_payload_chars=max_chars)


# ── SENSITIVE_TRACE_KEYS: exact-key redaction ─────────────────────────────────


def test_all_sensitive_trace_keys_are_redacted() -> None:
    """Every key in SENSITIVE_TRACE_KEYS must come out as [REDACTED]."""
    for key in SENSITIVE_TRACE_KEYS:
        result = redact_trace_value(key=key, value="some sensitive value")
        assert result == "[REDACTED]", (
            f"Expected '[REDACTED]' for key '{key}', got {result!r}"
        )


def test_sensitive_key_matching_is_case_insensitive() -> None:
    """Keys like 'Customer_Name' or 'OCR_TEXT' must also be redacted."""
    for key in SENSITIVE_TRACE_KEYS:
        upper = key.upper()
        result = redact_trace_value(key=upper, value="value")
        assert result == "[REDACTED]", (
            f"Case-insensitive match failed for key '{upper}'"
        )


# ── SENSITIVE_KEY_PARTS: substring redaction ──────────────────────────────────


def test_all_sensitive_key_parts_trigger_redaction() -> None:
    """Any key containing a SENSITIVE_KEY_PARTS substring must be redacted."""
    for part in SENSITIVE_KEY_PARTS:
        compound_key = f"supplier_{part}_field"
        result = redact_trace_value(key=compound_key, value="data")
        assert result == "[REDACTED]", (
            f"Expected '[REDACTED]' for key '{compound_key}' (part='{part}'), got {result!r}"
        )


def test_iban_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="bank_iban_number", value="GB29NWBK60161331926819")
    assert result == "[REDACTED]"


def test_routing_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="bank_routing_code", value="021000021")
    assert result == "[REDACTED]"


def test_account_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="supplier_account_number", value="12345678")
    assert result == "[REDACTED]"


def test_email_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="contact_email_address", value="user@example.com")
    assert result == "[REDACTED]"


def test_phone_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="supplier_phone", value="+84901234567")
    assert result == "[REDACTED]"


def test_tax_id_substring_triggers_redaction() -> None:
    result = redact_trace_value(key="company_tax_id_number", value="0123456789")
    assert result == "[REDACTED]"


def test_raw_underscore_prefix_triggers_redaction() -> None:
    result = redact_trace_value(key="raw_ocr_output", value="Invoice raw text")
    assert result == "[REDACTED]"


# ── Safe / non-sensitive values pass through ──────────────────────────────────


def test_safe_keys_pass_through_unchanged() -> None:
    safe_cases = [
        ("agent_name", "metadata_extractor"),
        ("provider_name", "paddleocr"),
        ("model_name", "llama3.1:8b"),
        ("attempts", 2),
        ("input_tokens", 512),
        ("output_tokens", 128),
        ("schema_name", "invoice_metadata"),
        ("workflow_run_id", "abc-123"),
        ("text_block_count", 7),
        ("duration_ms", 340),
        ("signal_codes", ["ERR_QA_MISMATCH"]),
    ]
    for key, value in safe_cases:
        result = redact_trace_value(key=key, value=value)
        assert result == value, (
            f"Safe key '{key}' was unexpectedly modified: {result!r}"
        )


# ── Nested dict recursive redaction ───────────────────────────────────────────


def test_nested_dict_sensitive_fields_are_redacted() -> None:
    payload = {
        "agent_name": "metadata_extractor",
        "result": {
            "supplier_name": "Acme Corp",
            "invoice_number": "INV-001",
            "customer_address": "123 Main St",
        },
    }
    redacted = redact_trace_value(key="result", value=payload["result"])
    assert isinstance(redacted, dict)
    assert redacted["supplier_name"] == "[REDACTED]"
    assert redacted["customer_address"] == "[REDACTED]"
    # invoice_number is not in the sensitive sets → passes through
    assert redacted["invoice_number"] == "INV-001"


def test_deeply_nested_sensitive_value_is_redacted() -> None:
    nested = {"outer": {"inner": {"supplier_name": "hidden"}}}
    result = redact_trace_value(key="outer", value=nested["outer"])
    assert isinstance(result, dict)
    assert isinstance(result["inner"], dict)
    assert result["inner"]["supplier_name"] == "[REDACTED]"  # type: ignore[index]


# ── List redaction ─────────────────────────────────────────────────────────────


def test_list_value_under_sensitive_key_is_redacted_as_whole() -> None:
    # When the key itself is sensitive the entire value — including a list — becomes
    # "[REDACTED]" (the list-iteration branch is never reached).
    result = redact_trace_value(key="messages", value=["msg1", "msg2", "msg3"])
    assert result == "[REDACTED]"


def test_list_of_safe_items_pass_through() -> None:
    result = redact_trace_value(key="signal_codes", value=["ERR_A", "ERR_B"])
    assert result == ["ERR_A", "ERR_B"]


def test_list_is_capped_at_20_items() -> None:
    big_list = list(range(30))
    result = redact_trace_value(key="safe_list", value=big_list)
    assert isinstance(result, list)
    assert len(result) == 20


# ── Long string truncation ─────────────────────────────────────────────────────


def test_long_safe_string_is_truncated_at_256_chars() -> None:
    long_value = "x" * 300
    result = redact_trace_value(key="safe_long_field", value=long_value)
    assert isinstance(result, str)
    assert len(result) <= 260  # 256 chars + "…"
    assert result.endswith("…")


def test_short_safe_string_is_not_truncated() -> None:
    short = "hello world"
    result = redact_trace_value(key="safe_field", value=short)
    assert result == short


# ── Payload size cap / truncation sentinel ─────────────────────────────────────


def test_oversized_payload_returns_truncation_sentinel() -> None:
    # Build a payload that is guaranteed to exceed 50 chars when JSON-encoded
    large_payload = {f"field_{i}": "x" * 20 for i in range(10)}
    result = minimize_trace_payload(large_payload, max_payload_chars=50)
    assert result.get("_truncated") is True
    assert "payload_chars" in result
    assert "payload_preview" in result


def test_payload_within_limit_is_returned_as_dict() -> None:
    payload = {"agent_name": "qa_agent", "attempts": 1}
    result = minimize_trace_payload(payload, max_payload_chars=4000)
    assert result["agent_name"] == "qa_agent"
    assert result["attempts"] == 1
    assert "_truncated" not in result


# ── RedactingTraceProvider end-to-end ─────────────────────────────────────────


def test_redacting_provider_redacts_supplier_name_in_event() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "llm.call.finished",
        {"agent_name": "metadata_extractor", "supplier_name": "Acme Corp", "attempts": 1},
    )
    event = sink.events[0]
    assert event.payload["supplier_name"] == "[REDACTED]"
    assert event.payload["agent_name"] == "metadata_extractor"
    assert event.payload["attempts"] == 1


def test_redacting_provider_redacts_all_pii_fields_in_single_event() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "ocr.call.finished",
        {
            "provider_name": "paddleocr",
            "supplier_name": "Autocare Vietnam",
            "supplier_address": "123 Hanoi St",
            "supplier_tax_id": "0123456789",
            "customer_name": "Jane Doe",
            "customer_tax_id": "9876543210",
            "customer_address": "456 HCM Ave",
            "ocr_text": "Full raw invoice text here",
            "text_block_count": 12,
        },
        correlation_id="ocr-trace-001",
    )
    event = sink.events[0]
    assert event.payload["supplier_name"] == "[REDACTED]"
    assert event.payload["supplier_address"] == "[REDACTED]"
    assert event.payload["supplier_tax_id"] == "[REDACTED]"
    assert event.payload["customer_name"] == "[REDACTED]"
    assert event.payload["customer_tax_id"] == "[REDACTED]"
    assert event.payload["customer_address"] == "[REDACTED]"
    assert event.payload["ocr_text"] == "[REDACTED]"
    # Safe fields survive
    assert event.payload["provider_name"] == "paddleocr"
    assert event.payload["text_block_count"] == 12
    assert event.correlation_id == "ocr-trace-001"


def test_redacting_provider_redacts_prompt_and_messages() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "llm.call.started",
        {
            "agent_name": "table_extractor",
            "prompt": "Extract table from: ...",
            "messages": ["user: invoice text", "assistant: ..."],
            "schema_name": "invoice_table",
        },
    )
    event = sink.events[0]
    assert event.payload["prompt"] == "[REDACTED]"
    # 'messages' key is sensitive → the whole list value becomes "[REDACTED]"
    assert event.payload["messages"] == "[REDACTED]"
    assert event.payload["schema_name"] == "invoice_table"


def test_redacting_provider_redacts_structured_output_and_raw_text() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "llm.call.finished",
        {
            "agent_name": "totals_extractor",
            "structured_output": {"grand_total": "1500.00", "supplier_name": "Shop A"},
            "raw_text": "Grand Total: 1500.00",
            "model_name": "llama3.1:8b",
        },
    )
    event = sink.events[0]
    assert event.payload["structured_output"] == "[REDACTED]"
    assert event.payload["raw_text"] == "[REDACTED]"
    assert event.payload["model_name"] == "llama3.1:8b"


def test_redacting_provider_passes_safe_qa_event_through() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "qa.error_signals.built",
        {
            "agent_name": "qa_validation_agent",
            "total_signal_count": 2,
            "correction_signal_count": 1,
            "blocking_signal_count": 0,
            "signal_codes": ["ERR_AMOUNT_INVALID"],
        },
    )
    event = sink.events[0]
    assert event.payload["agent_name"] == "qa_validation_agent"
    assert event.payload["total_signal_count"] == 2
    assert event.payload["signal_codes"] == ["ERR_AMOUNT_INVALID"]


def test_redacting_provider_review_task_event_exposes_only_safe_metadata() -> None:
    sink, provider = _make_redacting()
    provider.record_event(
        "review_task.created",
        {
            "review_task_id": "rt-abc-123",
            "task_type": "invoice_review",
            "target_type": "invoice",
            "status": "pending",
            "priority": "high",
            "reason_code": "ERR_AMOUNT_INVALID",
            "source_agent": "qa_validation_agent",
            "has_invoice_id": True,
            "evidence_ref_count": 3,
            "workflow_run_id": "wr-xyz-456",
            "workflow_status": "review_required",
        },
        correlation_id="corr-001",
    )
    event = sink.events[0]
    # All fields are safe metadata — none should be redacted
    assert event.payload["review_task_id"] == "rt-abc-123"
    assert event.payload["task_type"] == "invoice_review"
    assert event.payload["reason_code"] == "ERR_AMOUNT_INVALID"
    assert event.payload["has_invoice_id"] is True
    assert event.payload["evidence_ref_count"] == 3
    assert event.correlation_id == "corr-001"


def test_correlation_id_is_forwarded_by_redacting_provider() -> None:
    sink, provider = _make_redacting()
    provider.record_event("qa.validation_passed", {}, correlation_id="corr-42")
    assert sink.events[0].correlation_id == "corr-42"


def test_redacting_provider_handles_none_payload() -> None:
    sink, provider = _make_redacting()
    provider.record_event("ocr.call.started", None)
    assert len(sink.events) == 1
    assert sink.events[0].payload == {}


# ── NoOpTraceProvider ─────────────────────────────────────────────────────────


def test_noop_provider_drops_events_silently() -> None:
    noop = NoOpTraceProvider()
    # Should not raise; nothing to assert beyond that
    noop.record_event("any.event", {"supplier_name": "Acme"}, correlation_id="c1")


# ── InMemoryTraceProvider ─────────────────────────────────────────────────────


def test_in_memory_provider_records_events_in_order() -> None:
    provider = InMemoryTraceProvider()
    provider.record_event("event.one", {"step": 1})
    provider.record_event("event.two", {"step": 2})
    provider.record_event("event.three", {"step": 3})
    assert len(provider.events) == 3
    assert provider.events[0].name == "event.one"
    assert provider.events[1].name == "event.two"
    assert provider.events[2].name == "event.three"


def test_in_memory_provider_stores_correlation_id() -> None:
    provider = InMemoryTraceProvider()
    provider.record_event("event", {}, correlation_id="cid-99")
    assert provider.events[0].correlation_id == "cid-99"


# ── record_trace_event helper ─────────────────────────────────────────────────


def test_record_trace_event_is_noop_when_provider_is_none() -> None:
    # Must not raise
    record_trace_event(None, "event.name", {"supplier_name": "Acme"})


def test_record_trace_event_is_noop_when_provider_is_wrong_type() -> None:
    record_trace_event("not-a-provider", "event.name", {})


def test_record_trace_event_works_with_valid_provider() -> None:
    sink = InMemoryTraceProvider()
    record_trace_event(sink, "test.event", {"agent_name": "qa"}, correlation_id="c")
    assert len(sink.events) == 1
    assert sink.events[0].name == "test.event"
