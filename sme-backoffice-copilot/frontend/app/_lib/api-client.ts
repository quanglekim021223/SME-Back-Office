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
