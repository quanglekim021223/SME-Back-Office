import {
  DEFAULT_DEV_USER_ID,
  DEFAULT_DEV_USER_ROLE,
  getSelectedTenantId,
} from "./dev-context";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_PREFIX = process.env.NEXT_PUBLIC_API_PREFIX ?? "/api/v1";

type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
  };
  detail?: string;
};

type ApiRequestOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: BodyInit | Record<string, unknown> | null;
  headers?: HeadersInit;
};

export type DocumentType = "invoice" | "bank_statement" | "other";

export type MalwareScanResponse = {
  status: string;
  scanner_name: string;
  scanner_version: string | null;
  scanned_at: string | null;
  signature_version: string | null;
  threats: string[];
  details: Record<string, string>;
};

export type DocumentWorkflowTriggerResponse = {
  event_id: string;
  event_name: string;
  document_id: string;
  status: string;
};

export type DocumentUploadResponse = {
  id: string;
  tenant_id: string;
  document_type: DocumentType;
  status: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  content_hash: string;
  storage_uri: string;
  malware_scan: MalwareScanResponse;
  workflow_trigger: DocumentWorkflowTriggerResponse;
  duplicate: boolean;
};

export type ReviewTaskStatus =
  | "open"
  | "in_progress"
  | "resolved"
  | "cancelled";

export type ReviewTaskType =
  | "extraction"
  | "classification"
  | "reconciliation"
  | "policy"
  | "insight"
  | "other";

export type ReviewTaskPriority = "low" | "normal" | "high" | "urgent";

export type ReviewTaskSummaryResponse = {
  id: string;
  tenant_id: string;
  task_type: ReviewTaskType;
  target_type: string;
  status: ReviewTaskStatus;
  priority: ReviewTaskPriority;
  title: string;
  reason_code: string | null;
  due_at: string | null;
  source_agent: string | null;
  evidence_refs: string[];
  created_at: string;
  updated_at: string;
};

export type ReviewTaskDetailResponse = ReviewTaskSummaryResponse & {
  assigned_user_id: string | null;
  resolved_by_user_id: string | null;
  workflow_run_id: string | null;
  document_id: string | null;
  invoice_id: string | null;
  transaction_id: string | null;
  classification_proposal_id: string | null;
  reconciliation_id: string | null;
  insight_id: string | null;
  description: string | null;
  resolved_at: string | null;
  source_agent_version: string | null;
  metadata: Record<string, unknown>;
};

export type ReviewTaskListResponse = {
  items: ReviewTaskSummaryResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type ReviewTaskDecisionRequest = {
  comment?: string | null;
  reason_code?: string | null;
};

export type ReviewTaskDecisionResponse = {
  action: string;
  review_task: ReviewTaskDetailResponse;
  resource_type: string;
  resource_id: string;
  resource_status: string;
  audit_event_id: string;
};

export type ExtractedFieldsCorrectionRequest = ReviewTaskDecisionRequest & {
  corrected_fields: Record<string, unknown>;
};

export type ClassificationCorrectionRequest = ReviewTaskDecisionRequest & {
  proposed_category_id?: string | null;
  confidence?: string | null;
  rationale?: string | null;
  evidence_refs?: string[] | null;
  metadata?: Record<string, unknown> | null;
};

export type ReconciliationCorrectionRequest = ReviewTaskDecisionRequest & {
  match_type?: string | null;
  currency?: string | null;
  invoice_total_amount?: string | number | null;
  transaction_total_amount?: string | number | null;
  difference_amount?: string | number | null;
  confidence?: string | null;
  rationale?: string | null;
  evidence_refs?: string[] | null;
  metadata?: Record<string, unknown> | null;
};

export type ReviewTaskCorrectionResponse = {
  action: string;
  review_task: ReviewTaskDetailResponse;
  resource_type: string;
  superseded_resource_id: string;
  replacement_resource_id: string;
  replacement_resource_status: string;
  audit_event_id: string;
};

export type LocalMetricsResponse = {
  review_queue_size: Record<string, number>;
  review_actions: Record<string, number>;
  correction_rate: {
    correction_count: number;
    review_action_count: number;
    rate: number;
  };
};

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor({
    message,
    status,
    code,
    details,
  }: {
    message: string;
    status: number;
    code: string;
    details?: Record<string, unknown>;
  }) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function apiFetch<TResponse>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<TResponse> {
  const headers = new Headers(options.headers);
  const body = normalizeBody(options.body, headers);

  for (const [key, value] of Object.entries(getDevAuthHeaders())) {
    headers.set(key, value);
  }

  const response = await fetch(buildApiUrl(path), {
    ...options,
    body,
    headers,
  });

  if (!response.ok) {
    throw await buildApiClientError(response);
  }

  if (response.status === 204) {
    return undefined as TResponse;
  }

  return (await response.json()) as TResponse;
}

export function apiGet<TResponse>(path: string, options?: ApiRequestOptions) {
  return apiFetch<TResponse>(path, {
    ...options,
    method: "GET",
  });
}

export function apiPost<TResponse>(
  path: string,
  body?: ApiRequestOptions["body"],
  options?: ApiRequestOptions,
) {
  return apiFetch<TResponse>(path, {
    ...options,
    body,
    method: "POST",
  });
}

export function uploadDocument({
  documentType,
  file,
}: {
  documentType: DocumentType;
  file: File;
}) {
  const params = new URLSearchParams({
    document_type: documentType,
    filename: file.name,
  });

  return apiPost<DocumentUploadResponse>(
    `/documents/upload?${params.toString()}`,
    file,
    {
      headers: {
        "Content-Type": inferUploadMediaType(file),
      },
    },
  );
}

export function listReviewTasks({
  limit = 100,
  offset = 0,
  status,
  taskType,
}: {
  limit?: number;
  offset?: number;
  status?: ReviewTaskStatus;
  taskType?: ReviewTaskType;
} = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });

  if (status) {
    params.set("status", status);
  }

  if (taskType) {
    params.set("task_type", taskType);
  }

  return apiGet<ReviewTaskListResponse>(`/review-tasks?${params.toString()}`);
}

export function getReviewTask(reviewTaskId: string) {
  return apiGet<ReviewTaskDetailResponse>(`/review-tasks/${reviewTaskId}`);
}

export function approveReviewTask(
  reviewTaskId: string,
  decision: ReviewTaskDecisionRequest = {},
) {
  return apiPost<ReviewTaskDecisionResponse>(
    `/review-tasks/${reviewTaskId}/approve`,
    decision,
  );
}

export function rejectReviewTask(
  reviewTaskId: string,
  decision: ReviewTaskDecisionRequest = {},
) {
  return apiPost<ReviewTaskDecisionResponse>(
    `/review-tasks/${reviewTaskId}/reject`,
    decision,
  );
}

export function correctExtractedFields(
  reviewTaskId: string,
  correction: ExtractedFieldsCorrectionRequest,
) {
  return apiPost<ReviewTaskCorrectionResponse>(
    `/review-tasks/${reviewTaskId}/correct-extraction`,
    correction,
  );
}

export function correctClassification(
  reviewTaskId: string,
  correction: ClassificationCorrectionRequest,
) {
  return apiPost<ReviewTaskCorrectionResponse>(
    `/review-tasks/${reviewTaskId}/correct-classification`,
    correction,
  );
}

export function correctReconciliation(
  reviewTaskId: string,
  correction: ReconciliationCorrectionRequest,
) {
  return apiPost<ReviewTaskCorrectionResponse>(
    `/review-tasks/${reviewTaskId}/correct-reconciliation`,
    correction,
  );
}

export function getLocalMetrics() {
  return apiGet<LocalMetricsResponse>("/ops/metrics");
}

// ── Invoice types ────────────────────────────────────────────────────────────

export type InvoiceLineItemResponse = {
  id: string;
  invoice_id: string;
  line_number: number;
  description: string | null;
  product_code: string | null;
  quantity: string | null;
  unit_of_measure: string | null;
  unit_price_amount: string | null;
  net_amount: string | null;
  tax_rate: string | null;
  tax_amount: string | null;
  total_amount: string | null;
  currency: string | null;
  confidence: string | null;
};

export type ClassificationProposalResponse = {
  id: string;
  invoice_id: string | null;
  target_type: string;
  status: string;
  version: number;
  confidence: string | null;
  source_agent: string | null;
  rationale: string | null;
  evidence_refs: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type InvoiceReconciliationResponse = {
  id: string;
  reconciliation_id: string;
  transaction_id: string | null;
  status: string;
  allocated_amount: string;
  currency: string | null;
  confidence: string | null;
  allocation_method: string | null;
  reconciliation_status: string | null;
  rationale: string | null;
  evidence_refs: string[];
  metadata: Record<string, unknown>;
  transaction_description: string | null;
  transaction_posted_at: string | null;
  transaction_amount: string | null;
};

export type InvoiceResponse = {
  id: string;
  tenant_id: string;
  document_id: string | null;
  version: number;
  status: string;
  direction: string;
  invoice_number: string | null;
  supplier_name: string | null;
  supplier_tax_id: string | null;
  customer_name: string | null;
  customer_tax_id: string | null;
  issue_date: string | null;
  due_date: string | null;
  currency: string | null;
  subtotal_amount: string | null;
  tax_amount: string | null;
  total_amount: string | null;
  confidence: string | null;
  notes: string | null;
  supersedes_invoice_id: string | null;
  source_processing_run_id: string | null;
  line_items: InvoiceLineItemResponse[];
  classification_proposals: ClassificationProposalResponse[];
  reconciliations: InvoiceReconciliationResponse[];
  created_at: string;
  updated_at: string;
};

export type InvoiceListResponse = {
  items: Omit<
    InvoiceResponse,
    | "line_items"
    | "supplier_tax_id"
    | "customer_tax_id"
    | "notes"
    | "source_processing_run_id"
  >[];
  total: number;
  limit: number;
  offset: number;
};

export function listInvoices({
  limit = 50,
  offset = 0,
  status,
  excludeSuperseded = true,
}: {
  limit?: number;
  offset?: number;
  status?: string;
  excludeSuperseded?: boolean;
} = {}) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    exclude_superseded: String(excludeSuperseded),
  });

  if (status) {
    params.set("status", status);
  }

  return apiGet<InvoiceListResponse>(`/invoices?${params.toString()}`);
}

export function getInvoice(invoiceId: string) {
  return apiGet<InvoiceResponse>(`/invoices/${invoiceId}`);
}

export function formatApiError(error: unknown) {
  if (error instanceof ApiClientError) {
    return `${error.message} (${error.code}, ${error.status})`;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Unexpected frontend error.";
}

function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${API_PREFIX}${normalizedPath}`;
}

function inferUploadMediaType(file: File) {
  const extension = file.name.split(".").pop()?.toLowerCase();

  if (extension === "pdf") {
    return "application/pdf";
  }

  if (extension === "png") {
    return "image/png";
  }

  if (extension === "jpg" || extension === "jpeg") {
    return "image/jpeg";
  }

  if (extension === "csv") {
    return "text/csv";
  }

  return file.type || "application/octet-stream";
}

function getDevAuthHeaders() {
  return {
    "X-Tenant-ID": getSelectedTenantId(),
    "X-User-ID": DEFAULT_DEV_USER_ID,
    "X-User-Role": DEFAULT_DEV_USER_ROLE,
  };
}

function normalizeBody(
  body: ApiRequestOptions["body"],
  headers: Headers,
): BodyInit | null | undefined {
  if (body === undefined || body === null) {
    return body;
  }

  if (isBodyInit(body)) {
    return body;
  }

  headers.set("Content-Type", "application/json");
  return JSON.stringify(body);
}

function isBodyInit(body: ApiRequestOptions["body"]): body is BodyInit {
  return (
    body instanceof Blob ||
    body instanceof FormData ||
    body instanceof URLSearchParams ||
    body instanceof ArrayBuffer ||
    body instanceof ReadableStream
  );
}

async function buildApiClientError(response: Response) {
  let payload: ApiErrorBody | null = null;

  try {
    payload = (await response.json()) as ApiErrorBody;
  } catch {
    payload = null;
  }

  return new ApiClientError({
    status: response.status,
    code: payload?.error?.code ?? "api_error",
    message:
      payload?.error?.message ??
      payload?.detail ??
      `API request failed with status ${response.status}.`,
    details: payload?.error?.details,
  });
}
