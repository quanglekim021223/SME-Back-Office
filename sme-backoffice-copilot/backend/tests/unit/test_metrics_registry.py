from decimal import Decimal

from app.observability.metrics import InMemoryMetricsRegistry


def test_metrics_registry_records_endpoint_latency() -> None:
    registry = InMemoryMetricsRegistry()

    registry.record_endpoint(
        method="get",
        path="/health",
        status_code=200,
        duration_ms=12.34,
    )

    snapshot = registry.snapshot()
    metric = snapshot["endpoint_latency"]["GET /health 200"]
    assert metric["count"] == 1
    assert metric["avg_duration_ms"] == 12.34
    assert metric["failure_count"] == 0


def test_metrics_registry_records_provider_cost_retries_and_failures() -> None:
    registry = InMemoryMetricsRegistry()

    registry.record_provider_call(
        task_type="invoice_classification",
        provider_name="openai",
        model_name="gpt-test",
        attempts=2,
        duration_ms=125.5,
        success=True,
        input_tokens=100,
        output_tokens=50,
        total_cost=Decimal("0.0015"),
    )
    registry.record_provider_call(
        task_type="invoice_classification",
        provider_name="openai",
        model_name="gpt-test",
        attempts=1,
        duration_ms=50.0,
        success=False,
    )

    snapshot = registry.snapshot()
    metric = snapshot["provider_calls"]["invoice_classification:openai:gpt-test"]
    assert metric["count"] == 2
    assert metric["failure_count"] == 1
    assert metric["retry_count"] == 1
    assert metric["input_tokens"] == 100
    assert metric["output_tokens"] == 50
    assert metric["total_cost"] == "0.0015"
    assert snapshot["retry_counts"]["provider:openai"] == 1
    assert snapshot["failure_counts"]["provider:openai"] == 1


def test_metrics_registry_records_review_queue_size_and_correction_rate() -> None:
    registry = InMemoryMetricsRegistry()

    registry.record_review_queue_size(
        tenant_id="tenant-1",
        status="open",
        task_type=None,
        size=7,
    )
    registry.record_review_action(
        task_type="extraction",
        action="approve_proposal",
    )
    registry.record_review_action(
        task_type="classification",
        action="correct_classification",
    )

    snapshot = registry.snapshot()
    assert snapshot["review_queue_size"][
        "tenant:tenant-1:status:open:type:all"
    ] == 7
    assert snapshot["review_actions"] == {
        "classification:correct_classification": 1,
        "extraction:approve_proposal": 1,
    }
    assert snapshot["correction_rate"] == {
        "correction_count": 1,
        "review_action_count": 2,
        "rate": 0.5,
    }


def test_metrics_registry_records_queue_reliability_signals() -> None:
    registry = InMemoryMetricsRegistry()

    registry.record_queue_enqueued()
    registry.record_queue_started(queue_latency_ms=125.0)
    registry.record_queue_retry()
    registry.record_queue_started(queue_latency_ms=75.0)
    registry.record_queue_failed(dead_lettered=True)
    registry.record_queue_lost()

    queue = registry.snapshot()["workflow_queue"]
    assert queue["events"] == {
        "dead_lettered": 1,
        "enqueued": 1,
        "lost": 1,
        "retried": 1,
        "started": 2,
    }
    assert queue["running_jobs"] == 0
    assert queue["queue_latency"]["avg_duration_ms"] == 100.0
