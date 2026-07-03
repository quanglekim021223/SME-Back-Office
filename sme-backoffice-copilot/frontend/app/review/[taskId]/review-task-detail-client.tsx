"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../_components/status-states";
import {
  approveReviewTask,
  correctClassification,
  correctExtractedFields,
  correctReconciliation,
  formatApiError,
  getReviewTask,
  rejectReviewTask,
  type ClassificationCorrectionRequest,
  type ExtractedFieldsCorrectionRequest,
  type ReconciliationCorrectionRequest,
  type ReviewTaskDetailResponse,
  type ReviewTaskStatus,
  type ReviewTaskType,
} from "../../_lib/api-client";

type ReviewTaskDetailClientProps = {
  taskId: string;
};

type LoadState = "idle" | "loading" | "loaded" | "error";
type ActionState = "idle" | "running" | "succeeded" | "failed";

export function ReviewTaskDetailClient({
  taskId,
}: ReviewTaskDetailClientProps) {
  const [task, setTask] = useState<ReviewTaskDetailResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [correctionJson, setCorrectionJson] = useState("");

  async function refreshTask() {
    setLoadState("loading");
    setErrorMessage(null);

    try {
      const response = await getReviewTask(taskId);
      setTask(response);
      setCorrectionJson(defaultCorrectionJson(response.task_type));
      setLoadState("loaded");
    } catch (error) {
      setErrorMessage(formatApiError(error));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void refreshTask();
  }, [taskId]);

  const sourceReferences = useMemo(() => {
    if (!task) {
      return [];
    }

    return [
      task.document_id ? `document:${task.document_id}` : null,
      task.invoice_id ? `invoice:${task.invoice_id}` : null,
      task.transaction_id ? `transaction:${task.transaction_id}` : null,
      task.classification_proposal_id
        ? `classification:${task.classification_proposal_id}`
        : null,
      task.reconciliation_id
        ? `reconciliation:${task.reconciliation_id}`
        : null,
      task.insight_id ? `insight:${task.insight_id}` : null,
      ...task.evidence_refs,
    ].filter((reference): reference is string => Boolean(reference));
  }, [task]);

  async function runDecision(action: "approve" | "reject") {
    if (!task || actionState === "running") {
      return;
    }

    setActionState("running");
    setActionMessage(null);
    setErrorMessage(null);

    try {
      const request = {
        comment: comment.trim() || null,
        reason_code: action === "approve" ? "human_approved" : "human_rejected",
      };
      const response =
        action === "approve"
          ? await approveReviewTask(task.id, request)
          : await rejectReviewTask(task.id, request);

      setTask(response.review_task);
      setActionState("succeeded");
      setActionMessage(
        `${formatDecisionAction(response.action)} recorded. Audit event ${shortId(
          response.audit_event_id,
        )}.`,
      );
    } catch (error) {
      setActionState("failed");
      setErrorMessage(formatApiError(error));
    }
  }

  async function runCorrection() {
    if (!task || actionState === "running") {
      return;
    }

    setActionState("running");
    setActionMessage(null);
    setErrorMessage(null);

    try {
      const parsed = parseCorrectionJson(correctionJson);
      const baseRequest = {
        comment: comment.trim() || null,
        reason_code: "human_corrected",
      };
      const response = await submitCorrection(task, parsed, baseRequest);

      setTask(response.review_task);
      setActionState("succeeded");
      setActionMessage(
        `Correction saved. Replacement ${shortId(
          response.replacement_resource_id,
        )} superseded ${shortId(response.superseded_resource_id)}.`,
      );
    } catch (error) {
      setActionState("failed");
      setErrorMessage(formatApiError(error));
    }
  }

  if (loadState === "loading" && !task) {
    return (
      <LoadingState
        title="Loading review task"
        message="Fetching source links, evidence references, and review metadata..."
      />
    );
  }

  if (loadState === "error") {
    return (
      <ErrorState
        title="Review task could not be loaded"
        message={errorMessage ?? "The review task API returned an error."}
        action={
          <div className="action-row">
            <button
              className="button button-primary"
              onClick={() => void refreshTask()}
              type="button"
            >
              Try again
            </button>
            <Link className="button button-secondary" href="/review">
              Back to queue
            </Link>
          </div>
        }
      />
    );
  }

  if (!task) {
    return (
      <EmptyState
        title="No review task selected"
        message="Open a task from the review queue to inspect evidence and take an action."
        action={
          <Link className="button button-primary" href="/review">
            Open review queue
          </Link>
        }
      />
    );
  }

  const isActionable = task.status === "open" || task.status === "in_progress";
  const supportsCorrection = taskSupportsCorrection(task.task_type);

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Review task detail</p>
          <h2>{task.title}</h2>
          <p>
            Inspect the source evidence placeholder, then approve, reject, or
            submit a corrected proposal. Actions are persisted through the
            review API and recorded in the audit trail.
          </p>
        </div>
        <Link className="button button-secondary" href="/review">
          Back to queue
        </Link>
      </section>

      <section className="review-detail-layout">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">{formatTaskType(task.task_type)}</p>
              <h3>Decision context</h3>
            </div>
            <span className="status-pill status-pill-muted">
              {formatStatus(task.status)}
            </span>
          </div>

          <div className="detail-kv-grid">
            <DetailItem
              label="Priority"
              value={formatPriority(task.priority)}
            />
            <DetailItem label="Target" value={task.target_type} />
            <DetailItem label="Reason" value={task.reason_code ?? "Not set"} />
            <DetailItem
              label="Source agent"
              value={task.source_agent ?? "Not set"}
            />
            <DetailItem label="Created" value={formatDate(task.created_at)} />
            <DetailItem label="Updated" value={formatDate(task.updated_at)} />
          </div>

          <div className="review-description">
            <p className="eyebrow">Reviewer note</p>
            <p>
              {task.description ??
                "No detailed description is attached yet. Future workflow steps can provide validator errors, agent rationale, and proposed field diffs here."}
            </p>
          </div>

          <div className="review-description">
            <p className="eyebrow">Source evidence placeholder</p>
            <div className="source-evidence-placeholder">
              <div>
                <span>{task.target_type}</span>
                <strong>Evidence viewer reserved</strong>
                <p>
                  OCR text spans, PDF image regions, invoice line highlights,
                  bank transaction excerpts, and validator error signals will be
                  rendered in this area.
                </p>
              </div>
              <div className="evidence-grid-overlay" aria-hidden="true" />
            </div>
          </div>
        </article>

        <aside className="panel-card action-panel">
          <div>
            <p className="eyebrow">Human action</p>
            <h3>Approve, reject, or correct</h3>
          </div>

          <label className="form-field">
            <span>Reviewer comment</span>
            <textarea
              onChange={(event) => setComment(event.target.value)}
              placeholder="Add rationale for audit trail..."
              rows={4}
              value={comment}
            />
          </label>

          <div className="action-row">
            <button
              className="button button-primary"
              disabled={!isActionable || actionState === "running"}
              onClick={() => void runDecision("approve")}
              type="button"
            >
              Approve
            </button>
            <button
              className="button button-ghost"
              disabled={!isActionable || actionState === "running"}
              onClick={() => void runDecision("reject")}
              type="button"
            >
              Reject
            </button>
          </div>

          <div className="correction-card">
            <div>
              <p className="eyebrow">Correction payload</p>
              <p>
                JSON body mapped to the task type. Extraction uses
                <code> corrected_fields</code>; classification and
                reconciliation map directly to proposal fields.
              </p>
            </div>
            <textarea
              className="textarea-code"
              disabled={!supportsCorrection}
              onChange={(event) => setCorrectionJson(event.target.value)}
              rows={8}
              value={correctionJson}
            />
            <button
              className="button button-secondary"
              disabled={
                !isActionable ||
                !supportsCorrection ||
                actionState === "running"
              }
              onClick={() => void runCorrection()}
              type="button"
            >
              Submit correction
            </button>
          </div>

          {actionMessage ? (
            <div
              className="action-feedback action-feedback-success"
              role="status"
            >
              {actionMessage}
            </div>
          ) : null}
          {errorMessage ? (
            <div className="action-feedback action-feedback-error" role="alert">
              {errorMessage}
            </div>
          ) : null}
          {!isActionable ? (
            <small>
              This task is no longer actionable because its status is{" "}
              {formatStatus(task.status)}.
            </small>
          ) : null}
        </aside>
      </section>

      <section className="review-detail-layout">
        <article className="panel-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Traceability</p>
              <h3>Linked records</h3>
            </div>
            <span className="status-pill status-pill-muted">
              {sourceReferences.length} refs
            </span>
          </div>
          {sourceReferences.length > 0 ? (
            <div className="evidence-ref-list">
              {sourceReferences.map((reference) => (
                <code key={reference}>{reference}</code>
              ))}
            </div>
          ) : (
            <p>
              No source references have been attached yet. This task can still
              be reviewed, but future workflow persistence should add evidence
              refs for stronger traceability.
            </p>
          )}
        </article>

        <article className="panel-card">
          <div>
            <p className="eyebrow">Metadata</p>
            <h3>Workflow payload</h3>
          </div>
          {Object.keys(task.metadata).length > 0 ? (
            <dl className="metadata-list">
              {Object.entries(task.metadata).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{formatMetadataValue(value)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p>
              No metadata has been attached yet. Validator signals and proposal
              diffs can be persisted here later.
            </p>
          )}
        </article>
      </section>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

async function submitCorrection(
  task: ReviewTaskDetailResponse,
  parsed: Record<string, unknown>,
  baseRequest: { comment: string | null; reason_code: string },
) {
  if (task.task_type === "extraction") {
    const request: ExtractedFieldsCorrectionRequest = {
      ...baseRequest,
      corrected_fields: parsed,
    };
    return correctExtractedFields(task.id, request);
  }

  if (task.task_type === "classification") {
    const request: ClassificationCorrectionRequest = {
      ...parsed,
      ...baseRequest,
    };
    return correctClassification(task.id, request);
  }

  if (task.task_type === "reconciliation") {
    const request: ReconciliationCorrectionRequest = {
      ...parsed,
      ...baseRequest,
    };
    return correctReconciliation(task.id, request);
  }

  throw new Error(`Correction is not supported for ${task.task_type} tasks.`);
}

function taskSupportsCorrection(taskType: ReviewTaskType) {
  return (
    taskType === "extraction" ||
    taskType === "classification" ||
    taskType === "reconciliation"
  );
}

function defaultCorrectionJson(taskType: ReviewTaskType) {
  if (taskType === "extraction") {
    return JSON.stringify(
      {
        total_amount: "1240.00",
        confidence: "human_verified",
      },
      null,
      2,
    );
  }

  if (taskType === "classification") {
    return JSON.stringify(
      {
        confidence: "high",
        rationale: "Human reviewer corrected the category proposal.",
      },
      null,
      2,
    );
  }

  if (taskType === "reconciliation") {
    return JSON.stringify(
      {
        match_type: "manual",
        confidence: "high",
        rationale: "Human reviewer confirmed the invoice-to-bank match.",
      },
      null,
      2,
    );
  }

  return JSON.stringify(
    {
      note: "Correction is not supported for this task type.",
    },
    null,
    2,
  );
}

function parseCorrectionJson(value: string) {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Correction payload must be a JSON object.");
    }

    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("Correction payload is not valid JSON.");
    }

    throw error;
  }
}

function formatTaskType(taskType: ReviewTaskType) {
  return taskType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatStatus(status: ReviewTaskStatus) {
  return status
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatPriority(priority: ReviewTaskDetailResponse["priority"]) {
  return priority.charAt(0).toUpperCase() + priority.slice(1);
}

function formatDecisionAction(action: string) {
  return action
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatDate(value: string | null) {
  if (!value) {
    return "—";
  }

  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatMetadataValue(value: unknown) {
  if (value === null || value === undefined) {
    return "—";
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return JSON.stringify(value);
}

function shortId(value: string) {
  return value.slice(0, 8);
}
