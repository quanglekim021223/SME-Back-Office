"use client";

import { useEffect, useState } from "react";

import {
  formatApiError,
  getDocumentLineage,
  type WorkflowLineageResponse,
  type WorkflowLineageStep,
} from "../../_lib/api-client";

type LoadState = "loading" | "loaded" | "error";

function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDuration(durationMs: number | null) {
  if (durationMs === null) return "—";
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

function statusClass(status: string) {
  if (["succeeded", "completed"].includes(status)) {
    return "status-pill status-pill-success";
  }
  if (["retrying", "retry_requested", "review_required"].includes(status)) {
    return "status-pill status-pill-warning";
  }
  if (["failed", "lost", "dead_lettered"].includes(status)) {
    return "status-pill status-pill-error";
  }
  if (status === "running") return "status-pill status-pill-info";
  return "status-pill status-pill-muted";
}

function confidenceClass(confidence: string | null) {
  if (confidence === "high")
    return "lineage-confidence lineage-confidence-high";
  if (confidence === "medium") {
    return "lineage-confidence lineage-confidence-medium";
  }
  return "lineage-confidence lineage-confidence-low";
}

function StepNode({ step }: { step: WorkflowLineageStep }) {
  return (
    <li className="lineage-node">
      <span className="lineage-node-marker" aria-hidden="true">
        {step.step_index}
      </span>
      <details className="lineage-step" open={Boolean(step.correction_signal)}>
        <summary>
          <span className="lineage-step-title">
            <strong>{titleCase(step.agent_name)}</strong>
            <small>Attempt {step.attempt}</small>
          </span>
          <span className="lineage-step-meta">
            <span className={statusClass(step.status)}>
              {titleCase(step.status)}
            </span>
            <span className={confidenceClass(step.confidence)}>
              {step.confidence ? titleCase(step.confidence) : "Unknown"}
            </span>
            <code>{formatDuration(step.duration_ms)}</code>
          </span>
        </summary>

        <div className="lineage-step-details">
          <span>
            {formatTimestamp(step.started_at)} →{" "}
            {formatTimestamp(step.finished_at)}
          </span>
          {step.error_code ? (
            <p className="lineage-error">
              <strong>{step.error_code}</strong>
              {step.error_message ? ` — ${step.error_message}` : null}
            </p>
          ) : null}
          {step.correction_signal ? (
            <div className="lineage-correction-callout">
              <div>
                <span>Targeted retry</span>
                <code>{step.correction_signal.code}</code>
              </div>
              <strong>
                {titleCase(step.agent_name)} →{" "}
                {titleCase(step.correction_signal.target_agent)}
              </strong>
              <p>{step.correction_signal.message}</p>
              {step.correction_signal.instruction ? (
                <small>{step.correction_signal.instruction}</small>
              ) : null}
            </div>
          ) : null}
        </div>
      </details>
    </li>
  );
}

export function WorkflowLineageVisualizer({
  documentId,
}: {
  documentId: string;
}) {
  const [lineage, setLineage] = useState<WorkflowLineageResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function loadLineage() {
    setLoadState("loading");
    setErrorMessage(null);
    try {
      setLineage(await getDocumentLineage(documentId));
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void loadLineage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  return (
    <div className="proposal-section lineage-panel">
      <div className="card-header card-header-compact">
        <div>
          <p className="eyebrow">Execution lineage</p>
          <h4>Agent workflow trace</h4>
        </div>
        {lineage ? (
          <div className="action-row">
            <span className={statusClass(lineage.status)}>
              {titleCase(lineage.status)}
            </span>
            <code>{formatDuration(lineage.total_latency_ms)}</code>
          </div>
        ) : null}
      </div>

      {loadState === "loading" ? (
        <p className="muted-copy">Loading durable agent execution history…</p>
      ) : null}

      {loadState === "error" ? (
        <div className="lineage-load-error">
          <p>{errorMessage ?? "Workflow lineage could not be loaded."}</p>
          <button
            className="button button-ghost"
            onClick={() => void loadLineage()}
            type="button"
          >
            Retry
          </button>
        </div>
      ) : null}

      {lineage ? (
        <>
          <div className="lineage-summary">
            <span>
              <strong>{lineage.steps.length}</strong> steps
            </span>
            <span>
              <strong>{lineage.handoffs.length}</strong> handoffs
            </span>
            <span>
              <strong>{lineage.audit_history.length}</strong> human actions
            </span>
            <span>
              Stage <strong>{titleCase(lineage.stage ?? "unknown")}</strong>
            </span>
          </div>

          <ol className="lineage-timeline">
            {lineage.steps.map((step) => (
              <StepNode key={step.step_execution_id} step={step} />
            ))}
            {lineage.audit_history.map((event, index) => (
              <li
                className="lineage-node lineage-human-node"
                key={event.audit_event_id}
              >
                <span className="lineage-node-marker" aria-hidden="true">
                  H{index + 1}
                </span>
                <div className="lineage-step">
                  <div className="lineage-human-heading">
                    <span>
                      <small>Human audit node</small>
                      <strong>{titleCase(event.action)}</strong>
                    </span>
                    <span className="status-pill status-pill-info">Human</span>
                  </div>
                  <p>
                    {event.actor_name ??
                      event.actor_id ??
                      titleCase(event.actor_type)}{" "}
                    · {formatTimestamp(event.occurred_at)}
                  </p>
                  {event.comment ? (
                    <blockquote>{event.comment}</blockquote>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </div>
  );
}
