"use client";

import type { DragEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import {
  ApiClientError,
  cancelWorkflowRun,
  type DocumentType,
  type DocumentUploadResponse,
  type WorkflowRunStatusResponse,
  formatApiError,
  getWorkflowRun,
  uploadDocument,
} from "../_lib/api-client";

const uploadChecks = [
  "File type, size, and MIME validation",
  "Content hash for duplicate detection",
  "DocumentIngested workflow trigger",
];

const acceptedTypes = ["PDF", "PNG", "JPEG", "CSV"];
const isFileTypeActive = (type: string, docType: DocumentType) => {
  if (docType === "invoice") {
    return ["PDF", "PNG", "JPEG"].includes(type);
  }
  if (docType === "bank_statement") {
    return type === "CSV";
  }
  return true;
};
const acceptedFileExtensions = ".pdf,.png,.jpg,.jpeg,.csv";
const maxUploadSizeBytes = 20 * 1024 * 1024;

const documentModes: Array<{
  label: string;
  value: DocumentType;
}> = [
  { label: "Invoice or receipt", value: "invoice" },
  { label: "Bank statement", value: "bank_statement" },
  { label: "Other document", value: "other" },
];

type UploadActivity = {
  id: string;
  name: string;
  status: string;
  meta: string;
  tone: "positive" | "warning" | "danger" | "neutral";
};

const sampleUploads: UploadActivity[] = [
  {
    id: "sample-invoice",
    name: "invoice-cobalt-1042.pdf",
    status: "Pending review",
    meta: "Invoice - $2,480 - sample activity",
    tone: "warning",
  },
  {
    id: "sample-statement",
    name: "bank-statement-june.csv",
    status: "Parsed",
    meta: "Statement - 84 transactions - sample activity",
    tone: "positive",
  },
  {
    id: "sample-duplicate",
    name: "saas-vendor-receipt.png",
    status: "Duplicate",
    meta: "Expense - matched by content hash",
    tone: "neutral",
  },
];

type UploadStatus =
  | "idle"
  | "selected"
  | "uploading"
  | "uploaded"
  | "duplicate"
  | "unsupported"
  | "error";

type BatchUploadItem = {
  file: File;
  id: string;
  message: string;
  result?: DocumentUploadResponse;
  status: UploadStatus;
  workflowRun?: WorkflowRunStatusResponse;
};

export default function UploadPage() {
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [batchItems, setBatchItems] = useState<BatchUploadItem[]>([]);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [statusMessage, setStatusMessage] = useState(
    "Choose a file to start the local upload flow.",
  );
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResponse | null>(null);
  const [workflowRun, setWorkflowRun] =
    useState<WorkflowRunStatusResponse | null>(null);
  const [isCancellingWorkflow, setIsCancellingWorkflow] = useState(false);
  const [uploadActivities, setUploadActivities] = useState<UploadActivity[]>(
    [],
  );
  const [isDragging, setIsDragging] = useState(false);

  const selectedFile = selectedFiles.at(0) ?? null;
  const fileValidationError = selectedFile
    ? validateSelectedFile(selectedFile)
    : null;
  const isUploading = uploadStatus === "uploading";
  const readyFileCount = batchItems.filter(
    (item) => item.status === "selected",
  ).length;
  const workflowRunId = uploadResult?.workflow_trigger.workflow_run_id;
  const batchWorkflowRunIds = useMemo(
    () =>
      batchItems
        .map((item) => item.result?.workflow_trigger.workflow_run_id)
        .filter((workflowRunId): workflowRunId is string =>
          Boolean(workflowRunId),
        )
        .join(","),
    [batchItems],
  );
  const activityItems =
    uploadActivities.length > 0 ? uploadActivities : sampleUploads;

  const lifecycleSteps = useMemo(
    () => buildLifecycleSteps(uploadResult, uploadStatus, workflowRun),
    [uploadResult, uploadStatus, workflowRun],
  );

  useEffect(() => {
    if (!workflowRunId || batchItems.length > 1) {
      return;
    }

    let isCurrent = true;
    let timeoutId: number | undefined;

    const pollWorkflow = async () => {
      try {
        const nextWorkflowRun = await getWorkflowRun(workflowRunId);
        if (!isCurrent) {
          return;
        }
        setWorkflowRun(nextWorkflowRun);
        if (!nextWorkflowRun.progress.is_terminal) {
          timeoutId = window.setTimeout(() => {
            void pollWorkflow();
          }, 1250);
        }
      } catch {
        if (isCurrent) {
          timeoutId = window.setTimeout(() => {
            void pollWorkflow();
          }, 2500);
        }
      }
    };

    void pollWorkflow();
    return () => {
      isCurrent = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [batchItems.length, workflowRunId]);

  useEffect(() => {
    let isCurrent = true;
    let timeoutId: number | undefined;
    let pendingWorkflowRunIds = batchWorkflowRunIds
      ? batchWorkflowRunIds.split(",")
      : [];

    const pollBatchWorkflows = async () => {
      const progressUpdates = await Promise.all(
        pendingWorkflowRunIds.map(async (workflowRunId) => {
          try {
            return await getWorkflowRun(workflowRunId);
          } catch {
            return null;
          }
        }),
      );

      if (!isCurrent) {
        return;
      }

      const completedIds = new Set<string>();
      const updatesById = new Map<string, WorkflowRunStatusResponse>();
      for (const progress of progressUpdates) {
        if (!progress) {
          continue;
        }
        updatesById.set(progress.id, progress);
        if (progress.progress.is_terminal) {
          completedIds.add(progress.id);
        }
      }

      if (updatesById.size > 0) {
        setBatchItems((items) =>
          items.map((item) => {
            const workflowRunId = item.result?.workflow_trigger.workflow_run_id;
            const nextWorkflowRun = workflowRunId
              ? updatesById.get(workflowRunId)
              : undefined;
            return nextWorkflowRun
              ? { ...item, workflowRun: nextWorkflowRun }
              : item;
          }),
        );
      }

      pendingWorkflowRunIds = pendingWorkflowRunIds.filter(
        (workflowRunId) => !completedIds.has(workflowRunId),
      );
      if (pendingWorkflowRunIds.length > 0) {
        timeoutId = window.setTimeout(() => {
          void pollBatchWorkflows();
        }, 1250);
      }
    };

    if (batchItems.length > 1 && pendingWorkflowRunIds.length > 0) {
      void pollBatchWorkflows();
    }
    return () => {
      isCurrent = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [batchItems.length, batchWorkflowRunIds]);

  function handleFileSelection(files: File[]) {
    if (isUploading) {
      return;
    }

    setSelectedFiles(files);
    setUploadResult(null);
    setWorkflowRun(null);

    if (files.length === 0) {
      setBatchItems([]);
      setUploadStatus("idle");
      setStatusMessage("Choose a file to start the local upload flow.");
      return;
    }

    const nextItems = files.map((file, index) => {
      const validationError = validateSelectedFile(file);
      return {
        file,
        id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
        message: validationError?.message ?? "Ready to upload.",
        status: validationError?.status ?? "selected",
      } satisfies BatchUploadItem;
    });
    const validFileCount = nextItems.filter(
      (item) => item.status === "selected",
    ).length;

    setBatchItems(nextItems);
    setUploadStatus(validFileCount > 0 ? "selected" : nextItems[0].status);
    setStatusMessage(
      `${validFileCount} of ${files.length} file${files.length === 1 ? "" : "s"} ready to upload as ${formatDocumentType(documentType)}.`,
    );
  }

  async function handleUpload() {
    const queuedItems = batchItems.filter((item) => item.status === "selected");
    if (queuedItems.length === 0) {
      setStatusMessage("Choose at least one valid file before uploading.");
      return;
    }

    setUploadStatus("uploading");
    setWorkflowRun(null);
    setStatusMessage(
      `Uploading ${queuedItems.length} document${queuedItems.length === 1 ? "" : "s"}...`,
    );

    let acceptedCount = 0;
    for (const item of queuedItems) {
      setBatchItems((items) =>
        updateBatchItem(items, item.id, {
          message: "Sending file to the backend...",
          status: "uploading",
        }),
      );

      try {
        const result = await uploadDocument({ documentType, file: item.file });
        acceptedCount += 1;
        setUploadResult(result);
        setBatchItems((items) =>
          updateBatchItem(items, item.id, {
            message: "Accepted and queued for background processing.",
            result,
            status: "uploaded",
          }),
        );
        setUploadActivities((items) =>
          [buildUploadActivity(result), ...items].slice(0, 5),
        );
      } catch (error) {
        const outcome = formatBatchUploadError(error);
        setBatchItems((items) => updateBatchItem(items, item.id, outcome));
        if (outcome.status === "duplicate") {
          setUploadActivities((items) =>
            [
              {
                id: `${item.file.name}-duplicate-${Date.now()}`,
                meta: "Rejected by tenant-scoped content hash",
                name: item.file.name,
                status: "Duplicate",
                tone: "neutral",
              } satisfies UploadActivity,
              ...items,
            ].slice(0, 5),
          );
        }
      }
    }

    setUploadStatus(acceptedCount > 0 ? "uploaded" : "error");
    setStatusMessage(
      acceptedCount > 0
        ? `${acceptedCount} document${acceptedCount === 1 ? "" : "s"} accepted. OCR, CSV parsing, and review workflows continue in the background.`
        : "No documents were accepted. Review the per-file errors below.",
    );
  }

  async function handleCancelWorkflow() {
    if (!workflowRunId || !workflowRun || workflowRun.status !== "queued") {
      return;
    }

    setIsCancellingWorkflow(true);
    try {
      const cancelledWorkflow = await cancelWorkflowRun(workflowRunId);
      setWorkflowRun(cancelledWorkflow);
      setStatusMessage(
        "Queued workflow cancelled. The document was not processed.",
      );
    } catch (error) {
      setStatusMessage(formatApiError(error));
    } finally {
      setIsCancellingWorkflow(false);
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setIsDragging(false);
    if (isUploading) {
      return;
    }
    handleFileSelection(Array.from(event.dataTransfer.files));
  }

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Document intake</p>
          <h2>Upload invoices and bank statements.</h2>
          <p>
            Validate documents before agent workflows create extraction and
            review proposals.
          </p>
        </div>
        <span className="status-pill">Upload API ready</span>
      </section>

      <section className="upload-layout">
        <form
          className={[
            "upload-dropzone",
            isDragging ? "upload-dropzone-is-dragging" : null,
            isUploading ? "upload-dropzone-is-processing" : null,
          ]
            .filter(Boolean)
            .join(" ")}
          onDragLeave={() => setIsDragging(false)}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDrop={handleDrop}
          onSubmit={(event) => {
            event.preventDefault();
            void handleUpload();
          }}
        >
          <div className="upload-toolbar" aria-label="Document type selector">
            {documentModes.map((mode) => (
              <button
                aria-pressed={documentType === mode.value}
                className={
                  documentType === mode.value
                    ? "toolbar-chip toolbar-chip-active"
                    : "toolbar-chip"
                }
                disabled={isUploading}
                key={mode.value}
                onClick={() => {
                  setDocumentType(mode.value);
                  if (selectedFiles.length > 0) {
                    setStatusMessage(
                      `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected as ${formatDocumentType(
                        mode.value,
                      )}.`,
                    );
                  }
                }}
                type="button"
              >
                {mode.label}
              </button>
            ))}
          </div>

          <div className="upload-icon" aria-hidden="true">
            DOC
          </div>
          <h3>Drop files here or browse</h3>
          <p>
            Invoices, receipts, and bank statements will be validated before the
            workflow starts.
          </p>

          <input
            accept={acceptedFileExtensions}
            className="visually-hidden"
            disabled={isUploading}
            id="document-upload-input"
            onChange={(event) => {
              handleFileSelection(Array.from(event.currentTarget.files ?? []));
              // Permit selecting the same file or batch again after a previous run.
              event.currentTarget.value = "";
            }}
            type="file"
            multiple
          />

          <div className="upload-action-row">
            <label
              aria-disabled={isUploading}
              className={
                isUploading
                  ? "button button-secondary button-disabled"
                  : "button button-secondary"
              }
              htmlFor={isUploading ? undefined : "document-upload-input"}
            >
              Choose files
            </label>
            <button
              className="button button-primary"
              disabled={readyFileCount === 0 || isUploading}
              type="submit"
            >
              {isUploading
                ? "Uploading..."
                : readyFileCount > 0
                  ? `Upload ${readyFileCount} file${readyFileCount === 1 ? "" : "s"}`
                  : "Upload files"}
            </button>
          </div>

          {isUploading ? (
            <UploadProcessingCard documentType={documentType} />
          ) : null}

          <div className="file-type-row" aria-label="Accepted file types">
            {acceptedTypes.map((type) => {
              const active = isFileTypeActive(type, documentType);
              return (
                <span
                  key={type}
                  className={
                    active
                      ? "file-type-badge-active"
                      : "file-type-badge-inactive"
                  }
                >
                  {type}
                </span>
              );
            })}
          </div>

          <UploadStatusCard
            canCancelWorkflow={workflowRun?.status === "queued"}
            file={selectedFile}
            isCancellingWorkflow={isCancellingWorkflow}
            message={statusMessage}
            onCancelWorkflow={() => {
              void handleCancelWorkflow();
            }}
            result={uploadResult}
            status={uploadStatus}
            workflowRun={workflowRun}
          />

          {batchItems.length > 1 ? (
            <BatchUploadList items={batchItems} />
          ) : null}
        </form>

        <aside className="panel-card">
          <div>
            <p className="eyebrow">Preflight checks</p>
            <h3>What happens before processing</h3>
          </div>
          <div className="check-list">
            {uploadChecks.map((check) => (
              <div className="check-row" key={check}>
                <span className="check-marker" aria-hidden="true">
                  OK
                </span>
                <p>{check}</p>
              </div>
            ))}
          </div>

          <div className="lifecycle-panel">
            <div>
              <p className="eyebrow">Processing status</p>
              <h3>Document lifecycle</h3>
            </div>
            <div className="lifecycle-list">
              {lifecycleSteps.map((step) => (
                <div
                  className={`lifecycle-row lifecycle-row-${step.state}`}
                  key={step.label}
                >
                  <span aria-hidden="true" />
                  <div>
                    <strong>{step.label}</strong>
                    <small>{step.value}</small>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </section>

      <section className="panel-card">
        <div className="card-header">
          <div>
            <p className="eyebrow">Recent activity</p>
            <h3>Upload status</h3>
          </div>
          <span className="status-pill status-pill-muted">
            {uploadActivities.length > 0 ? "Live session" : "Mock data"}
          </span>
        </div>
        <div className="activity-list">
          {activityItems.map((upload) => (
            <div className="activity-row" key={upload.id}>
              <div>
                <strong>{upload.name}</strong>
                <span>{upload.meta}</span>
              </div>
              <em className={`activity-status activity-status-${upload.tone}`}>
                {upload.status}
              </em>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function UploadProcessingCard({
  documentType,
}: {
  documentType: DocumentType;
}) {
  const processingLabel =
    documentType === "bank_statement"
      ? "Parsing statement transactions"
      : "Running OCR and extraction workflow";

  return (
    <div className="upload-processing-card" role="status" aria-live="polite">
      <div className="upload-processing-header">
        <span className="upload-processing-dot" aria-hidden="true" />
        <div>
          <strong>Processing document</strong>
          <p>
            Keep this page open while the upload is accepted and the workflow is
            prepared.
          </p>
        </div>
      </div>
      <div className="upload-processing-track" aria-hidden="true" />
      <ol className="upload-processing-steps">
        <li>Sending file to backend</li>
        <li>Validating file and checking duplicates</li>
        <li>{processingLabel}</li>
      </ol>
    </div>
  );
}

function UploadStatusCard({
  canCancelWorkflow,
  file,
  isCancellingWorkflow,
  message,
  onCancelWorkflow,
  result,
  status,
  workflowRun,
}: {
  canCancelWorkflow: boolean;
  file: File | null;
  isCancellingWorkflow: boolean;
  message: string;
  onCancelWorkflow: () => void;
  result: DocumentUploadResponse | null;
  status: UploadStatus;
  workflowRun: WorkflowRunStatusResponse | null;
}) {
  return (
    <div className={`upload-status-card upload-status-card-${status}`}>
      <div>
        <strong>{formatUploadStatus(status)}</strong>
        <p>{message}</p>
      </div>
      {workflowRun ? (
        <div className="workflow-progress" aria-live="polite">
          <div className="workflow-progress-heading">
            <span>{workflowRun.progress.label}</span>
            <strong>{workflowRun.progress.percent}%</strong>
          </div>
          <div
            aria-label={`Workflow progress ${workflowRun.progress.percent}%`}
            aria-valuemax={100}
            aria-valuemin={0}
            aria-valuenow={workflowRun.progress.percent}
            className="workflow-progress-track"
            role="progressbar"
          >
            <span style={{ width: `${workflowRun.progress.percent}%` }} />
          </div>
          <small>
            {formatStatus(workflowRun.status)}
            {workflowRun.progress.current_agent
              ? ` - ${formatStatus(workflowRun.progress.current_agent)}`
              : null}
          </small>
        </div>
      ) : null}
      {file ? (
        <dl>
          <div>
            <dt>File</dt>
            <dd>{file.name}</dd>
          </div>
          <div>
            <dt>Size</dt>
            <dd>{formatBytes(file.size)}</dd>
          </div>
          {result ? (
            <>
              <div>
                <dt>Document ID</dt>
                <dd>{result.id}</dd>
              </div>
              <div>
                <dt>Hash</dt>
                <dd>{formatHash(result.content_hash)}</dd>
              </div>
              {result.workflow_trigger.workflow_run_id ? (
                <div>
                  <dt>Workflow run</dt>
                  <dd>
                    {formatIdentifier(result.workflow_trigger.workflow_run_id)}
                  </dd>
                </div>
              ) : null}
            </>
          ) : null}
        </dl>
      ) : null}
      {canCancelWorkflow ? (
        <button
          className="button button-secondary workflow-cancel-button"
          disabled={isCancellingWorkflow}
          onClick={onCancelWorkflow}
          type="button"
        >
          {isCancellingWorkflow ? "Cancelling..." : "Cancel queued workflow"}
        </button>
      ) : null}
    </div>
  );
}

function BatchUploadList({ items }: { items: BatchUploadItem[] }) {
  return (
    <div className="batch-upload-list" aria-label="Selected upload files">
      <div className="batch-upload-heading">
        <strong>Batch upload</strong>
        <span>{items.length} files</span>
      </div>
      {items.map((item) => (
        <div className="batch-upload-row" key={item.id}>
          <div className="batch-upload-copy">
            <strong>{item.file.name}</strong>
            <span>{item.message}</span>
            {item.workflowRun ? (
              <>
                <div className="batch-workflow-heading">
                  <span>{item.workflowRun.progress.label}</span>
                  <span>{item.workflowRun.progress.percent}%</span>
                </div>
                <div
                  aria-label={`Workflow progress for ${item.file.name}`}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={item.workflowRun.progress.percent}
                  className={`batch-workflow-progress batch-workflow-progress-${workflowLifecycleState(
                    item.workflowRun.status,
                  )}`}
                  role="progressbar"
                >
                  <span
                    style={{ width: `${item.workflowRun.progress.percent}%` }}
                  />
                </div>
                <small>
                  {formatStatus(item.workflowRun.status)}
                  {item.workflowRun.current_agent
                    ? ` - ${item.workflowRun.current_agent}`
                    : ""}
                </small>
              </>
            ) : item.status === "uploaded" ? (
              <small>Waiting for the first workflow update.</small>
            ) : null}
          </div>
          <em
            className={`activity-status activity-status-${batchItemTone(item)}`}
          >
            {batchItemStatusLabel(item)}
          </em>
        </div>
      ))}
    </div>
  );
}

function validateSelectedFile(file: File): {
  message: string;
  status: Extract<UploadStatus, "unsupported" | "error">;
} | null {
  if (file.size <= 0) {
    return {
      message: "The selected file is empty. Choose a document with content.",
      status: "error",
    };
  }

  if (file.size > maxUploadSizeBytes) {
    return {
      message: `The selected file is larger than ${formatBytes(
        maxUploadSizeBytes,
      )}.`,
      status: "error",
    };
  }

  if (!/\.(pdf|png|jpe?g|csv)$/i.test(file.name)) {
    return {
      message: "Unsupported file type. Upload PDF, PNG, JPEG, or CSV files.",
      status: "unsupported",
    };
  }

  return null;
}

function updateBatchItem(
  items: BatchUploadItem[],
  id: string,
  update: Partial<BatchUploadItem>,
) {
  return items.map((item) => (item.id === id ? { ...item, ...update } : item));
}

function formatBatchUploadError(
  error: unknown,
): Pick<BatchUploadItem, "message" | "status"> {
  if (error instanceof ApiClientError && error.code === "duplicate_document") {
    return {
      message: `Duplicate document. Existing document: ${String(
        error.details?.document_id ?? "unknown",
      )}.`,
      status: "duplicate",
    };
  }

  if (
    error instanceof ApiClientError &&
    error.code === "unsupported_mime_type"
  ) {
    return { message: error.message, status: "unsupported" };
  }

  return { message: formatApiError(error), status: "error" };
}

function batchStatusTone(status: UploadStatus): UploadActivity["tone"] {
  if (status === "uploaded") {
    return "positive";
  }
  if (status === "duplicate" || status === "unsupported") {
    return "warning";
  }
  if (status === "error") {
    return "danger";
  }
  return "neutral";
}

function batchItemTone(item: BatchUploadItem): UploadActivity["tone"] {
  if (!item.workflowRun) {
    return batchStatusTone(item.status);
  }

  const state = workflowLifecycleState(item.workflowRun.status);
  if (state === "error") {
    return "danger";
  }
  if (state === "done") {
    return "positive";
  }
  return "neutral";
}

function batchItemStatusLabel(item: BatchUploadItem) {
  if (!item.workflowRun) {
    return formatUploadStatus(item.status);
  }

  return `${formatStatus(item.workflowRun.status)} ${item.workflowRun.progress.percent}%`;
}

function buildLifecycleSteps(
  result: DocumentUploadResponse | null,
  uploadStatus: UploadStatus,
  workflowRun: WorkflowRunStatusResponse | null,
) {
  if (!result) {
    const isUploading = uploadStatus === "uploading";
    const isBlocked =
      uploadStatus === "duplicate" ||
      uploadStatus === "unsupported" ||
      uploadStatus === "error";

    return [
      {
        label: "Upload request",
        state: isUploading ? "current" : isBlocked ? "error" : "pending",
        value: isUploading
          ? "Sending file bytes and awaiting backend acknowledgement"
          : "Waiting for a valid file",
      },
      {
        label: "Preflight validation",
        state: isUploading ? "current" : "pending",
        value: isUploading
          ? "Checking MIME, size, and duplicate hash"
          : "Runs before workflow starts",
      },
      {
        label: "Workflow trigger",
        state: "pending",
        value: "Publishes DocumentIngested event after acceptance",
      },
      {
        label: "Processing",
        state: "pending",
        value: "OCR and extraction continue through the workflow runtime",
      },
    ] as const;
  }

  return [
    {
      label: "Upload request",
      state: "done",
      value: `Document status: ${formatStatus(result.status)}`,
    },
    {
      label: "Malware scan",
      state: "done",
      value: `${formatStatus(result.malware_scan.status)} by ${
        result.malware_scan.scanner_name
      }`,
    },
    {
      label: "Workflow trigger",
      state: "done",
      value: `${result.workflow_trigger.event_name} ${formatStatus(
        result.workflow_trigger.status,
      )}`,
    },
    {
      label: "Processing",
      state: workflowRun
        ? workflowLifecycleState(workflowRun.status)
        : "current",
      value: workflowRun
        ? `${workflowRun.progress.label} (${workflowRun.progress.percent}%)`
        : result.workflow_trigger.workflow_run_id
          ? `Queued in the background as ${formatIdentifier(
              result.workflow_trigger.workflow_run_id,
            )}`
          : "Queued for the controlled workflow runtime",
    },
  ] as const;
}

function buildUploadActivity(result: DocumentUploadResponse): UploadActivity {
  return {
    id: result.id,
    name: result.original_filename,
    status: formatStatus(result.status),
    meta: `${formatDocumentType(result.document_type)} - ${formatBytes(
      result.size_bytes,
    )} - ${formatHash(result.content_hash)}`,
    tone: "positive",
  };
}

function formatDocumentType(documentType: DocumentType) {
  const labels: Record<DocumentType, string> = {
    bank_statement: "bank statement",
    invoice: "invoice",
    other: "other document",
  };

  return labels[documentType];
}

function formatUploadStatus(status: UploadStatus) {
  const labels: Record<UploadStatus, string> = {
    duplicate: "Duplicate detected",
    error: "Upload needs attention",
    idle: "No file selected",
    selected: "Ready to upload",
    unsupported: "Unsupported file",
    uploaded: "Upload accepted",
    uploading: "Uploading file",
  };

  return labels[status];
}

function formatStatus(status: string) {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatHash(hash: string) {
  return `${hash.slice(0, 10)}...${hash.slice(-6)}`;
}

function formatIdentifier(identifier: string) {
  return `${identifier.slice(0, 8)}...${identifier.slice(-6)}`;
}

function workflowLifecycleState(status: string) {
  if (["completed", "review_required", "cancelled"].includes(status)) {
    return "done";
  }
  if (["failed", "lost", "dead_lettered"].includes(status)) {
    return "error";
  }
  return "current";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
