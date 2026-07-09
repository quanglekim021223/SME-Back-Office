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
type PendingAction = "approve" | "reject" | "correction" | null;

export function ReviewTaskDetailClient({
  taskId,
}: ReviewTaskDetailClientProps) {
  const [task, setTask] = useState<ReviewTaskDetailResponse | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [actionState, setActionState] = useState<ActionState>("idle");
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
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

  const workflowMetadata = useMemo(
    () => buildWorkflowMetadataView(task?.metadata ?? {}),
    [task?.metadata],
  );
  const proposalView = useMemo(
    () => buildProposalView(task, workflowMetadata),
    [task, workflowMetadata],
  );

  async function runDecision(action: "approve" | "reject") {
    if (!task || actionState === "running") {
      return;
    }

    setActionState("running");
    setPendingAction(action);
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
    } finally {
      setPendingAction(null);
    }
  }

  async function runCorrection() {
    if (!task || actionState === "running") {
      return;
    }

    setActionState("running");
    setPendingAction("correction");
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
    } finally {
      setPendingAction(null);
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
  const actionProgress = getActionProgress(pendingAction);

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
              disabled={actionState === "running" || !isActionable}
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
              {pendingAction === "approve" ? "Approving..." : "Approve"}
            </button>
            <button
              className="button button-ghost"
              disabled={!isActionable || actionState === "running"}
              onClick={() => void runDecision("reject")}
              type="button"
            >
              {pendingAction === "reject" ? "Rejecting..." : "Reject"}
            </button>
          </div>

          {actionProgress ? (
            <div className="action-progress" role="status" aria-live="polite">
              <div className="action-progress-header">
                <span className="action-progress-dot" aria-hidden="true" />
                <strong>{actionProgress.title}</strong>
              </div>
              <p>{actionProgress.message}</p>
              <div className="action-progress-bar" aria-hidden="true" />
            </div>
          ) : null}

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
              disabled={!supportsCorrection || actionState === "running"}
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
              {pendingAction === "correction"
                ? "Submitting correction..."
                : "Submit correction"}
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

      <section className="review-evidence-layout">
        <article className="panel-card panel-card-large">
          <div className="card-header">
            <div>
              <p className="eyebrow">{proposalView.eyebrow}</p>
              <h3>{proposalView.title}</h3>
            </div>
            <span className="status-pill status-pill-muted">
              {proposalView.statusLabel}
            </span>
          </div>

          <div className="proposal-summary-grid">
            {proposalView.fields.map((field) => (
              <ProposalField
                emphasis={field.emphasis}
                key={field.label}
                label={field.label}
                value={field.value}
              />
            ))}
          </div>

          {proposalView.summary ? (
            <div className="proposal-section proposal-note">
              <p className="eyebrow">{proposalView.summaryLabel}</p>
              <p>{proposalView.summary}</p>
            </div>
          ) : null}

          {proposalView.chips.length > 0 ? (
            <div className="proposal-section">
              <p className="eyebrow">{proposalView.chipLabel}</p>
              <div className="evidence-ref-list">
                {proposalView.chips.map((chip, index) => (
                  <code key={`${chip}-${index}`}>{chip}</code>
                ))}
              </div>
            </div>
          ) : null}

          {proposalView.kind === "extraction" ? (
            <LineItemsPreview lineItems={workflowMetadata.lineItems} />
          ) : null}
        </article>

        <article className="panel-card">
          <div>
            <p className="eyebrow">Diagnostics</p>
            <h3>OCR and provider status</h3>
          </div>

          <div className="debug-stack">
            <div className="debug-block">
              <div className="card-header card-header-compact">
                <h4>OCR text preview</h4>
                <span className="status-pill status-pill-muted">
                  {workflowMetadata.ocrPreview.length} chars
                </span>
              </div>
              {workflowMetadata.ocrPreview ? (
                <pre className="ocr-preview-text">
                  {workflowMetadata.ocrPreview}
                </pre>
              ) : (
                <p className="muted-copy">No OCR preview attached.</p>
              )}
            </div>

            <div className="debug-block">
              <div className="card-header card-header-compact">
                <h4>Provider extraction errors</h4>
                <span className="status-pill status-pill-muted">
                  {workflowMetadata.providerErrors.length}
                </span>
              </div>
              {workflowMetadata.providerErrors.length > 0 ? (
                <div className="provider-error-list">
                  {workflowMetadata.providerErrors.map((error, index) => (
                    <details key={`${error.agentName}-${index}`}>
                      <summary>
                        <span>{error.agentName ?? "provider"}</span>
                        <code>{error.errorCode ?? "ERR_UNKNOWN"}</code>
                      </summary>
                      <pre>{error.errorMessage ?? "No error details."}</pre>
                    </details>
                  ))}
                </div>
              ) : (
                <p className="muted-copy">No provider errors recorded.</p>
              )}
            </div>
          </div>
        </article>
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
              {sourceReferences.map((reference, index) => (
                <code key={`${reference}-${index}`}>{reference}</code>
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
            <h3>Raw workflow payload</h3>
          </div>
          {Object.keys(task.metadata).length > 0 ? (
            <details className="debug-disclosure">
              <summary>
                Open raw JSON metadata
                <span>{Object.keys(task.metadata).length} keys</span>
              </summary>
              <pre className="debug-code">{prettyJson(task.metadata)}</pre>
            </details>
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

function ProposalField({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string | null;
  emphasis?: boolean;
}) {
  return (
    <div
      className={
        emphasis ? "proposal-field proposal-field-emphasis" : "proposal-field"
      }
    >
      <span>{label}</span>
      <strong>{value || "—"}</strong>
    </div>
  );
}

function LineItemsPreview({
  lineItems,
}: {
  lineItems: WorkflowMetadataView["lineItems"];
}) {
  return (
    <div className="proposal-section">
      <div className="card-header card-header-compact">
        <div>
          <p className="eyebrow">Line items</p>
          <h4>Extracted table rows</h4>
        </div>
        <span className="status-pill status-pill-muted">
          {lineItems.length} rows
        </span>
      </div>
      {lineItems.length > 0 ? (
        <div className="line-items-table-wrap">
          <table className="compact-data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Description</th>
                <th>Qty</th>
                <th>Unit</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {lineItems.map((item, index) => (
                <tr key={`${item.description}-${index}`}>
                  <td>{item.lineNumber ?? index + 1}</td>
                  <td>{item.description ?? "—"}</td>
                  <td>{item.quantity ?? "—"}</td>
                  <td>{item.unitPrice ?? "—"}</td>
                  <td>{item.lineTotal ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted-copy">
          No line items were attached to this proposal yet.
        </p>
      )}
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

function getActionProgress(action: PendingAction) {
  if (action === "approve") {
    return {
      title: "Recording approval",
      message:
        "Approve proposal is being persisted, the audit event is being written, and downstream workflow steps may continue.",
    };
  }

  if (action === "reject") {
    return {
      title: "Recording rejection",
      message:
        "Reject decision is being persisted and the audit event is being written.",
    };
  }

  if (action === "correction") {
    return {
      title: "Saving correction",
      message:
        "The corrected proposal is being saved, superseded records are being linked, and the audit event is being written.",
    };
  }

  return null;
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

function shortId(value: string) {
  return value.slice(0, 8);
}

type WorkflowMetadataView = {
  assemblyStatus: string | null;
  invoiceNumber: string | null;
  supplier: string | null;
  customer: string | null;
  issueDate: string | null;
  dueDate: string | null;
  currency: string | null;
  totalAmount: string | null;
  lineItems: Array<{
    lineNumber: string | null;
    description: string | null;
    quantity: string | null;
    unitPrice: string | null;
    lineTotal: string | null;
  }>;
  ocrPreview: string;
  providerErrors: Array<{
    agentName: string | null;
    errorCode: string | null;
    errorMessage: string | null;
  }>;
};

type ProposalView = {
  kind: ReviewTaskType;
  eyebrow: string;
  title: string;
  statusLabel: string;
  summaryLabel: string;
  summary: string | null;
  chipLabel: string;
  chips: string[];
  fields: Array<{
    label: string;
    value: string | null;
    emphasis?: boolean;
  }>;
};

function buildProposalView(
  task: ReviewTaskDetailResponse | null,
  workflowMetadata: WorkflowMetadataView,
): ProposalView {
  if (task?.task_type === "classification") {
    return buildClassificationProposalView(task);
  }

  if (task?.task_type === "reconciliation") {
    return buildReconciliationProposalView(task);
  }

  return {
    kind: "extraction",
    eyebrow: "Extracted proposal",
    title: "Invoice fields ready for review",
    statusLabel: workflowMetadata.assemblyStatus ?? "Draft",
    summaryLabel: "Reviewer note",
    summary: null,
    chipLabel: "Evidence",
    chips: [],
    fields: [
      { label: "Invoice #", value: workflowMetadata.invoiceNumber },
      { label: "Supplier", value: workflowMetadata.supplier },
      { label: "Customer", value: workflowMetadata.customer },
      { label: "Issue date", value: workflowMetadata.issueDate },
      { label: "Due date", value: workflowMetadata.dueDate },
      {
        label: "Total",
        value: formatMoneyDisplay(
          workflowMetadata.totalAmount,
          workflowMetadata.currency,
        ),
        emphasis: true,
      },
    ],
  };
}

function buildClassificationProposalView(
  task: ReviewTaskDetailResponse,
): ProposalView {
  const metadata = task.metadata;
  const confidence = getDisplayValue(metadata.confidence);
  const score = getDisplayValue(metadata.score);
  const matchedKeywords = getArray(metadata.matched_keywords)
    .map(getDisplayValue)
    .filter((value): value is string => Boolean(value));
  const matchedRules = getArray(metadata.matched_rule_ids)
    .map(getDisplayValue)
    .filter((value): value is string => Boolean(value));

  return {
    kind: "classification",
    eyebrow: "Classification proposal",
    title: "Accounting category decision",
    statusLabel: confidence ? `${titleCase(confidence)} confidence` : "Review",
    summaryLabel: "Rationale",
    summary: getDisplayValue(metadata.rationale),
    chipLabel: "Matched signals",
    chips: [...matchedKeywords, ...matchedRules],
    fields: [
      {
        label: "Category",
        value: titleCase(getDisplayValue(metadata.proposed_category_code)),
        emphasis: true,
      },
      {
        label: "Direction",
        value: titleCase(getDisplayValue(metadata.proposed_direction)),
      },
      {
        label: "Category type",
        value: titleCase(getDisplayValue(metadata.proposed_category_type)),
      },
      { label: "Confidence", value: titleCase(confidence) },
      { label: "Score", value: score },
      {
        label: "Linked invoice",
        value: task.invoice_id ? shortId(task.invoice_id) : "—",
      },
    ],
  };
}

function buildReconciliationProposalView(
  task: ReviewTaskDetailResponse,
): ProposalView {
  const metadata = task.metadata;
  const currency = getDisplayValue(metadata.currency);
  const invoiceTotal = getDisplayValue(metadata.invoice_total_amount);
  const transactionTotal = getDisplayValue(metadata.transaction_total_amount);
  const difference = getDisplayValue(metadata.difference_amount);
  const reviewReason = getDisplayValue(metadata.review_reason);
  const candidateCount = getDisplayValue(metadata.candidate_count);

  return {
    kind: "reconciliation",
    eyebrow: "Reconciliation proposal",
    title: "Invoice-to-bank match decision",
    statusLabel: reviewReason
      ? (titleCase(reviewReason) ?? "Review")
      : "Review",
    summaryLabel: "Match rationale",
    summary:
      reviewReason === "awaiting_transaction_match"
        ? "No bank transaction has been confirmed yet. Review the invoice amount and confirm a manual match or leave this item open for later reconciliation."
        : getDisplayValue(metadata.rationale),
    chipLabel: "Match context",
    chips: task.reconciliation_id
      ? [`reconciliation:${task.reconciliation_id}`]
      : [],
    fields: [
      {
        label: "Invoice total",
        value: formatMoneyDisplay(invoiceTotal, currency),
        emphasis: true,
      },
      {
        label: "Transaction total",
        value: formatMoneyDisplay(transactionTotal, currency),
      },
      {
        label: "Difference",
        value: formatMoneyDisplay(difference, currency),
      },
      { label: "Currency", value: currency },
      {
        label: "Confidence",
        value: titleCase(getDisplayValue(metadata.confidence)),
      },
      { label: "Candidates", value: candidateCount },
    ],
  };
}

function buildWorkflowMetadataView(
  metadata: Record<string, unknown>,
): WorkflowMetadataView {
  const draft = getRecord(metadata.assembled_invoice_draft);
  const groups = getRecord(draft?.groups);
  const metadataGroup = getRecord(groups?.metadata);
  const tableGroup = getRecord(groups?.table);
  const totalsGroup = getRecord(groups?.totals);
  const lineItems = getArray(tableGroup?.line_items)
    .map((item) => getRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      lineNumber: getDisplayValue(item.line_number),
      description: getDisplayValue(item.description),
      quantity: getDisplayValue(item.quantity),
      unitPrice: getDisplayValue(item.unit_price),
      lineTotal: getDisplayValue(item.line_total),
    }));
  const providerErrors = getArray(metadata.provider_extraction_errors)
    .map((error) => getRecord(error))
    .filter((error): error is Record<string, unknown> => Boolean(error))
    .map((error) => ({
      agentName: getDisplayValue(error.agent_name),
      errorCode: getDisplayValue(error.error_code),
      errorMessage: getDisplayValue(error.error_message),
    }));

  return {
    assemblyStatus: titleCase(getDisplayValue(draft?.assembly_status)),
    invoiceNumber: getDisplayValue(metadataGroup?.invoice_number),
    supplier: getDisplayValue(metadataGroup?.supplier_name),
    customer: getDisplayValue(metadataGroup?.customer_name),
    issueDate: getDisplayValue(metadataGroup?.issue_date),
    dueDate: getDisplayValue(metadataGroup?.due_date),
    currency: getDisplayValue(totalsGroup?.currency ?? metadataGroup?.currency),
    totalAmount: getDisplayValue(totalsGroup?.total_amount),
    lineItems,
    ocrPreview: getDisplayValue(metadata.ocr_text_preview) ?? "",
    providerErrors,
  };
}

function getRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  return value as Record<string, unknown>;
}

function getArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function getDisplayValue(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "string") {
    return value || null;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return null;
}

function formatMoneyDisplay(amount: string | null, currency: string | null) {
  if (!amount) {
    return null;
  }

  return currency ? `${currency} ${amount}` : amount;
}

function titleCase(value: string | null) {
  if (!value) {
    return null;
  }

  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}
