"""Small in-memory metrics registry for local operations visibility."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from threading import RLock


@dataclass(slots=True)
class AggregateMetric:
    """Aggregate counters for one metric key."""

    count: int = 0
    failure_count: int = 0
    retry_count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: Decimal = Decimal("0.00")

    def record(
        self,
        *,
        duration_ms: float | None = None,
        failed: bool = False,
        retries: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_cost: Decimal = Decimal("0.00"),
    ) -> None:
        """Add one observation."""

        self.count += 1
        self.failure_count += int(failed)
        self.retry_count += retries
        if duration_ms is not None:
            self.total_duration_ms += duration_ms
            self.max_duration_ms = max(self.max_duration_ms, duration_ms)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost += total_cost

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly snapshot."""

        average = self.total_duration_ms / self.count if self.count else 0.0
        return {
            "count": self.count,
            "failure_count": self.failure_count,
            "retry_count": self.retry_count,
            "avg_duration_ms": round(average, 2),
            "max_duration_ms": round(self.max_duration_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_cost": str(self.total_cost),
        }


class InMemoryMetricsRegistry:
    """Process-local metrics store used until an external backend is added."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._endpoint_latency: dict[str, AggregateMetric] = {}
        self._agent_steps: dict[str, AggregateMetric] = {}
        self._provider_calls: dict[str, AggregateMetric] = {}
        self._retry_counts: dict[str, int] = {}
        self._failure_counts: dict[str, int] = {}
        self._review_queue_size: dict[str, int] = {}
        self._review_actions: dict[str, int] = {}

    def reset(self) -> None:
        """Clear all metrics, primarily for tests."""

        with self._lock:
            self._endpoint_latency.clear()
            self._agent_steps.clear()
            self._provider_calls.clear()
            self._retry_counts.clear()
            self._failure_counts.clear()
            self._review_queue_size.clear()
            self._review_actions.clear()

    def record_endpoint(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Record one completed HTTP request."""

        key = f"{method.upper()} {path} {status_code}"
        endpoint_key = f"endpoint:{method.upper()} {path}"
        with self._lock:
            metric = self._endpoint_latency.setdefault(key, AggregateMetric())
            metric.record(duration_ms=duration_ms, failed=status_code >= 500)
            if status_code >= 500:
                self._failure_counts[endpoint_key] = (
                    self._failure_counts.get(endpoint_key, 0) + 1
                )

    def record_agent_step(
        self,
        *,
        agent_name: str,
        status: str,
        duration_ms: float | None,
        attempt: int,
    ) -> None:
        """Record one workflow agent step."""

        key = f"{agent_name}:{status}"
        failed = status in {"failed", "retrying"}
        retries = max(attempt - 1, 0)
        with self._lock:
            self._agent_steps.setdefault(key, AggregateMetric()).record(
                duration_ms=duration_ms,
                failed=failed,
                retries=retries,
            )
            if retries:
                self._retry_counts[f"agent:{agent_name}"] = (
                    self._retry_counts.get(f"agent:{agent_name}", 0) + retries
                )
            if failed:
                self._failure_counts[f"agent:{agent_name}"] = (
                    self._failure_counts.get(f"agent:{agent_name}", 0) + 1
                )

    def record_workflow_retry(
        self,
        *,
        agent_name: str,
        retry_allowed: bool,
    ) -> None:
        """Record a workflow retry decision."""

        with self._lock:
            self._retry_counts[f"agent:{agent_name}"] = (
                self._retry_counts.get(f"agent:{agent_name}", 0) + 1
            )
            if not retry_allowed:
                self._failure_counts[f"retry_exhausted:{agent_name}"] = (
                    self._failure_counts.get(f"retry_exhausted:{agent_name}", 0) + 1
                )

    def record_provider_call(
        self,
        *,
        task_type: str,
        provider_name: str,
        model_name: str | None,
        attempts: int,
        duration_ms: float,
        success: bool,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_cost: Decimal = Decimal("0.00"),
    ) -> None:
        """Record one OCR or LLM provider call."""

        model_label = model_name or "unknown_model"
        key = f"{task_type}:{provider_name}:{model_label}"
        retries = max(attempts - 1, 0)
        with self._lock:
            self._provider_calls.setdefault(key, AggregateMetric()).record(
                duration_ms=duration_ms,
                failed=not success,
                retries=retries,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_cost=total_cost,
            )
            if retries:
                self._retry_counts[f"provider:{provider_name}"] = (
                    self._retry_counts.get(f"provider:{provider_name}", 0) + retries
                )
            if not success:
                self._failure_counts[f"provider:{provider_name}"] = (
                    self._failure_counts.get(f"provider:{provider_name}", 0) + 1
                )

    def record_review_queue_size(
        self,
        *,
        tenant_id: str,
        status: str,
        task_type: str | None,
        size: int,
    ) -> None:
        """Record the latest observed human review queue size."""

        task_type_label = task_type or "all"
        key = f"tenant:{tenant_id}:status:{status}:type:{task_type_label}"
        with self._lock:
            self._review_queue_size[key] = size

    def record_review_action(
        self,
        *,
        task_type: str,
        action: str,
    ) -> None:
        """Record one resolved human review action."""

        key = f"{task_type}:{action}"
        with self._lock:
            self._review_actions[key] = self._review_actions.get(key, 0) + 1

    def snapshot(self) -> dict[str, object]:
        """Return a stable snapshot of local metrics."""

        with self._lock:
            correction_count = sum(
                count
                for key, count in self._review_actions.items()
                if ":correct_" in key
            )
            review_action_count = sum(self._review_actions.values())
            correction_rate = (
                correction_count / review_action_count if review_action_count else 0.0
            )
            return {
                "endpoint_latency": {
                    key: metric.as_dict()
                    for key, metric in sorted(self._endpoint_latency.items())
                },
                "agent_steps": {
                    key: metric.as_dict()
                    for key, metric in sorted(self._agent_steps.items())
                },
                "provider_calls": {
                    key: metric.as_dict()
                    for key, metric in sorted(self._provider_calls.items())
                },
                "retry_counts": dict(sorted(self._retry_counts.items())),
                "failure_counts": dict(sorted(self._failure_counts.items())),
                "review_queue_size": dict(sorted(self._review_queue_size.items())),
                "review_actions": dict(sorted(self._review_actions.items())),
                "correction_rate": {
                    "correction_count": correction_count,
                    "review_action_count": review_action_count,
                    "rate": round(correction_rate, 4),
                },
            }


metrics_registry = InMemoryMetricsRegistry()
