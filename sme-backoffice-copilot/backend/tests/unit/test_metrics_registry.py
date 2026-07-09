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
