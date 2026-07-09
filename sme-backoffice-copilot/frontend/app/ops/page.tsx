"use client";

import { useEffect, useMemo, useState } from "react";

import { ErrorState, LoadingState } from "../_components/status-states";
import {
  formatApiError,
  getLocalMetrics,
  type AggregateMetricResponse,
  type LocalMetricsResponse,
} from "../_lib/api-client";

type MetricTone = "positive" | "neutral" | "warning";

type MetricRow = {
  key: string;
  metric: AggregateMetricResponse;
};

export default function OpsPage() {
  const [metrics, setMetrics] = useState<LocalMetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function loadMetrics() {
      setIsLoading(true);
      setError(null);

      try {
        const response = await getLocalMetrics();
        setMetrics(response);
      } catch (requestError) {
        setError(formatApiError(requestError));
      } finally {
        setIsLoading(false);
      }
    }

    void loadMetrics();
  }, []);

  const endpointRows = useMemo(
    () => topMetricRows(metrics?.endpoint_latency ?? {}, "max_duration_ms", 8),
    [metrics],
  );
  const providerRows = useMemo(
    () => topMetricRows(metrics?.provider_calls ?? {}, "failure_count", 8),
    [metrics],
  );
  const agentRows = useMemo(
    () => topMetricRows(metrics?.agent_steps ?? {}, "max_duration_ms", 8),
    [metrics],
  );
  const failureRows = useMemo(
    () => topCounterRows(metrics?.failure_counts ?? {}, 8),
    [metrics],
  );

  if (isLoading) {
    return (
      <LoadingState
        title="Loading local ops"
        message="Reading the in-process metrics snapshot..."
      />
    );
  }

  if (error || !metrics) {
    return (
      <ErrorState
        title="Could not load ops metrics"
        message={error ?? "The metrics endpoint returned no data."}
      />
    );
  }

  const openQueueSize = findOpenReviewQueueSize(metrics);
  const correctionRate = metrics.correction_rate.rate;
  const providerFailureCount = sumMetricField(
    Object.values(metrics.provider_calls),
    "failure_count",
  );
  const workflowFailureCount = sumWorkflowFailures(metrics.failure_counts);
  const slowestEndpoint = endpointRows[0];
  const totalCost = sumCurrency(
    Object.values(metrics.provider_calls).map((metric) => metric.total_cost),
  );

  const summaryCards = [
    {
      label: "Open review queue",
      value: String(openQueueSize),
      trend: openQueueSize > 10 ? "Backlog risk" : "Live gauge",
      tone: openQueueSize > 10 ? "warning" : "neutral",
      caption: "Latest observed open human review tasks for the active tenant.",
    },
    {
      label: "Provider failures",
      value: String(providerFailureCount),
      trend: providerFailureCount > 0 ? "Investigate" : "Clean",
      tone: providerFailureCount > 0 ? "warning" : "positive",
      caption: "OCR and LLM provider failures recorded in this server process.",
    },
    {
      label: "Workflow failures",
      value: String(workflowFailureCount),
      trend: workflowFailureCount > 0 ? "Needs review" : "Clean",
      tone: workflowFailureCount > 0 ? "warning" : "positive",
      caption: "Agent step failures and exhausted workflow retries.",
    },
    {
      label: "Slowest endpoint",
      value: slowestEndpoint
        ? formatMilliseconds(slowestEndpoint.metric.max_duration_ms)
        : "0 ms",
      trend: slowestEndpoint
        ? formatMetricLabel(slowestEndpoint.key)
        : "No traffic",
      tone:
        slowestEndpoint && slowestEndpoint.metric.max_duration_ms > 2000
          ? "warning"
          : "neutral",
      caption: "Highest max latency seen by the local HTTP middleware.",
    },
    {
      label: "Correction rate",
      value: formatPercent(correctionRate),
      trend:
        metrics.correction_rate.review_action_count > 0
          ? `${metrics.correction_rate.correction_count}/${metrics.correction_rate.review_action_count} corrected`
          : "No decisions yet",
      tone: correctionRate >= 0.25 ? "warning" : "positive",
      caption: "Share of review actions that submitted corrected data.",
    },
    {
      label: "Model cost",
      value: `$${totalCost}`,
      trend: "Process total",
      tone: "neutral",
      caption: "Estimated provider cost accumulated in local metrics.",
    },
  ] satisfies Array<{
    label: string;
    value: string;
    trend: string;
    tone: MetricTone;
    caption: string;
  }>;

  return (
    <div className="page-stack">
      <section className="dashboard-hero dashboard-hero-compact">
        <div className="hero-copy">
          <span className="status-pill status-pill-inverted">
            Local operations
          </span>
          <h2>Runtime health for the local back-office workflow.</h2>
          <p>
            This page reads the process-local metrics snapshot from
            /api/v1/ops/metrics. Values reset when the backend process restarts.
          </p>
        </div>

        <aside
          className="dashboard-readiness-card"
          aria-label="Ops data readiness"
        >
          <p className="eyebrow">Metrics coverage</p>
          <div className="readiness-list">
            <ReadinessItem label="HTTP latency" value="Live" />
            <ReadinessItem label="Agent steps" value="Live" />
            <ReadinessItem label="Provider calls" value="Live" />
            <ReadinessItem label="Review queue" value="Live" />
          </div>
        </aside>
      </section>

      <section className="metric-grid" aria-label="Local operations summary">
        {summaryCards.map((card) => (
          <article className="metric-card" key={card.label}>
            <div className="card-header">
              <span>{card.label}</span>
              <em className={`metric-trend metric-trend-${card.tone}`}>
                {card.trend}
              </em>
            </div>
            <strong>{card.value}</strong>
            <p>{card.caption}</p>
          </article>
        ))}
      </section>

      <section className="ops-panel-grid">
        <MetricsTable
          caption="Endpoint latency"
          eyebrow="HTTP"
          emptyMessage="No endpoint traffic has been recorded yet."
          rows={endpointRows}
        />
        <MetricsTable
          caption="Provider calls"
          eyebrow="OCR and LLM"
          emptyMessage="No provider calls have been recorded yet."
          rows={providerRows}
          showTokens
        />
      </section>

      <section className="ops-panel-grid">
        <MetricsTable
          caption="Agent step latency"
          eyebrow="Workflow"
          emptyMessage="No workflow agent steps have been recorded yet."
          rows={agentRows}
        />

        <CounterTable
          caption="Failures and retries"
          counters={failureRows}
          retryCounts={metrics.retry_counts}
        />
      </section>
    </div>
  );
}

function MetricsTable({
  caption,
  eyebrow,
  emptyMessage,
  rows,
  showTokens = false,
}: {
  caption: string;
  eyebrow: string;
  emptyMessage: string;
  rows: MetricRow[];
  showTokens?: boolean;
}) {
  return (
    <article className="panel-card panel-card-large">
      <div className="card-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h3>{caption}</h3>
        </div>
        <span className="status-pill status-pill-muted">
          {rows.length} rows
        </span>
      </div>
      {rows.length ? (
        <div className="table-shell">
          <table className="data-table ops-metrics-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Count</th>
                <th>Avg</th>
                <th>Max</th>
                <th>Failures</th>
                <th>Retries</th>
                {showTokens ? <th>Tokens</th> : null}
                {showTokens ? <th>Cost</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, metric }) => (
                <tr key={key}>
                  <td>
                    <em>{formatMetricLabel(key)}</em>
                  </td>
                  <td>{metric.count}</td>
                  <td>{formatMilliseconds(metric.avg_duration_ms)}</td>
                  <td>{formatMilliseconds(metric.max_duration_ms)}</td>
                  <td>{metric.failure_count}</td>
                  <td>{metric.retry_count}</td>
                  {showTokens ? (
                    <td>{metric.input_tokens + metric.output_tokens}</td>
                  ) : null}
                  {showTokens ? <td>${metric.total_cost}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="ops-empty-note">{emptyMessage}</p>
      )}
    </article>
  );
}

function CounterTable({
  caption,
  counters,
  retryCounts,
}: {
  caption: string;
  counters: Array<{ key: string; value: number }>;
  retryCounts: Record<string, number>;
}) {
  const retryRows = topCounterRows(retryCounts, 8);

  return (
    <article className="panel-card">
      <div className="card-header">
        <div>
          <p className="eyebrow">Reliability</p>
          <h3>{caption}</h3>
        </div>
        <span className="status-pill status-pill-muted">
          {counters.length + retryRows.length} signals
        </span>
      </div>

      <div className="ops-counter-list">
        <CounterGroup
          emptyMessage="No failures recorded."
          label="Failure counts"
          rows={counters}
        />
        <CounterGroup
          emptyMessage="No retries recorded."
          label="Retry counts"
          rows={retryRows}
        />
      </div>
    </article>
  );
}

function CounterGroup({
  emptyMessage,
  label,
  rows,
}: {
  emptyMessage: string;
  label: string;
  rows: Array<{ key: string; value: number }>;
}) {
  return (
    <section className="ops-counter-group">
      <h4>{label}</h4>
      {rows.length ? (
        rows.map((row) => (
          <div className="ops-counter-row" key={row.key}>
            <span>{formatMetricLabel(row.key)}</span>
            <strong>{row.value}</strong>
          </div>
        ))
      ) : (
        <p className="ops-empty-note">{emptyMessage}</p>
      )}
    </section>
  );
}

function ReadinessItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function topMetricRows(
  metrics: Record<string, AggregateMetricResponse>,
  sortKey: "failure_count" | "max_duration_ms",
  limit: number,
) {
  return Object.entries(metrics)
    .map(([key, metric]) => ({ key, metric }))
    .sort((left, right) => {
      const primary = right.metric[sortKey] - left.metric[sortKey];
      if (primary !== 0) {
        return primary;
      }
      return right.metric.max_duration_ms - left.metric.max_duration_ms;
    })
    .slice(0, limit);
}

function topCounterRows(counters: Record<string, number>, limit: number) {
  return Object.entries(counters)
    .map(([key, value]) => ({ key, value }))
    .sort((left, right) => right.value - left.value)
    .slice(0, limit);
}

function findOpenReviewQueueSize(metrics: LocalMetricsResponse) {
  const entry = Object.entries(metrics.review_queue_size).find(([key]) =>
    key.includes(":status:open:type:all"),
  );
  return entry?.[1] ?? 0;
}

function sumMetricField(
  metrics: AggregateMetricResponse[],
  field: "failure_count" | "retry_count",
) {
  return metrics.reduce((total, metric) => total + metric[field], 0);
}

function sumWorkflowFailures(failureCounts: Record<string, number>) {
  return Object.entries(failureCounts).reduce((total, [key, value]) => {
    if (key.startsWith("agent:") || key.startsWith("retry_exhausted:")) {
      return total + value;
    }
    return total;
  }, 0);
}

function sumCurrency(values: string[]) {
  const total = values.reduce((sum, value) => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? sum + parsed : sum;
  }, 0);
  return total.toFixed(4);
}

function formatMetricLabel(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
      "{id}",
    )
    .replaceAll("/api/v1", "")
    .replace(/^([A-Z]+)\s+(.+)\s+(\d{3})$/, "$1 $2 · $3")
    .replaceAll(":", " / ");
}

function formatMilliseconds(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)} s`;
  }
  return `${Math.round(value)} ms`;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}
