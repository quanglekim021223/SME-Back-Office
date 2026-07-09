"use client";

import type { DragEvent } from "react";
import { useMemo, useState } from "react";

import {
  ApiClientError,
  type DocumentType,
  type DocumentUploadResponse,
  formatApiError,
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

export default function UploadPage() {
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [statusMessage, setStatusMessage] = useState(
    "Choose a file to start the local upload flow.",
  );
  const [uploadResult, setUploadResult] =
    useState<DocumentUploadResponse | null>(null);
  const [uploadActivities, setUploadActivities] = useState<UploadActivity[]>(
    [],
  );
  const [isDragging, setIsDragging] = useState(false);

  const fileValidationError = selectedFile
    ? validateSelectedFile(selectedFile)
    : null;
  const isUploading = uploadStatus === "uploading";
  const activityItems =
    uploadActivities.length > 0 ? uploadActivities : sampleUploads;

  const lifecycleSteps = useMemo(
    () => buildLifecycleSteps(uploadResult, uploadStatus),
    [uploadResult, uploadStatus],
  );

  function handleFileSelection(file: File | null) {
    if (isUploading) {
      return;
    }

    setSelectedFile(file);
    setUploadResult(null);

    if (!file) {
      setUploadStatus("idle");
      setStatusMessage("Choose a file to start the local upload flow.");
      return;
    }

    const validationError = validateSelectedFile(file);
    if (validationError) {
      setUploadStatus(validationError.status);
      setStatusMessage(validationError.message);
      return;
    }

    setUploadStatus("selected");
    setStatusMessage(
      `${file.name} is ready to upload as ${formatDocumentType(documentType)}.`,
    );
  }

  async function handleUpload() {
    if (!selectedFile) {
      setStatusMessage("Choose a file before uploading.");
      return;
    }

    const validationError = validateSelectedFile(selectedFile);
    if (validationError) {
      setUploadStatus(validationError.status);
      setStatusMessage(validationError.message);
      return;
    }

    setUploadStatus("uploading");
    setStatusMessage("Uploading document to the backend...");

    try {
      const result = await uploadDocument({
        documentType,
        file: selectedFile,
      });

      setUploadResult(result);
      setUploadStatus("uploaded");
      setStatusMessage(
        "Upload accepted. The DocumentIngested trigger was published.",
      );
      setUploadActivities((items) =>
        [buildUploadActivity(result), ...items].slice(0, 5),
      );
    } catch (error) {
      if (
        error instanceof ApiClientError &&
        error.code === "duplicate_document"
      ) {
        setUploadStatus("duplicate");
        setStatusMessage(
          `Duplicate document detected. Existing document: ${String(
            error.details?.document_id ?? "unknown",
          )}.`,
        );
        const duplicateActivity: UploadActivity = {
          id: `${selectedFile.name}-duplicate-${Date.now()}`,
          meta: "Rejected by tenant-scoped content hash",
          name: selectedFile.name,
          status: "Duplicate",
          tone: "neutral",
        };
        setUploadActivities((items) =>
          [duplicateActivity, ...items].slice(0, 5),
        );
        return;
      }

      if (
        error instanceof ApiClientError &&
        error.code === "unsupported_mime_type"
      ) {
        setUploadStatus("unsupported");
        setStatusMessage(error.message);
        return;
      }

      setUploadStatus("error");
      setStatusMessage(formatApiError(error));
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setIsDragging(false);
    if (isUploading) {
      return;
    }
    handleFileSelection(event.dataTransfer.files.item(0));
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
                  if (selectedFile && !fileValidationError) {
                    setStatusMessage(
                      `${selectedFile.name} is ready to upload as ${formatDocumentType(
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
            onChange={(event) =>
              handleFileSelection(event.currentTarget.files?.item(0) ?? null)
            }
            type="file"
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
              Choose file
            </label>
            <button
              className="button button-primary"
              disabled={
                !selectedFile || Boolean(fileValidationError) || isUploading
              }
              type="submit"
            >
              {isUploading ? "Processing..." : "Upload file"}
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
            file={selectedFile}
            message={statusMessage}
            result={uploadResult}
            status={uploadStatus}
          />
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
  file,
  message,
  result,
  status,
}: {
  file: File | null;
  message: string;
  result: DocumentUploadResponse | null;
  status: UploadStatus;
}) {
  return (
    <div className={`upload-status-card upload-status-card-${status}`}>
      <div>
        <strong>{formatUploadStatus(status)}</strong>
        <p>{message}</p>
      </div>
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
            </>
          ) : null}
        </dl>
      ) : null}
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

function buildLifecycleSteps(
  result: DocumentUploadResponse | null,
  uploadStatus: UploadStatus,
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
      state: "current",
      value: "Queued for the controlled workflow runtime",
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

function formatBytes(bytes: number) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
