# Security And Privacy Conventions

This document records the Phase 10 conventions used by the local MVP. It is
not a production security certification; it is the baseline every production
deployment must satisfy before real tenant data is processed.

## Secret Management

Local development may read secrets from `.env`, but `.env` is a developer-only
bootstrap file and must never be committed, copied into logs, or used as the
source of truth in shared environments.

Production and shared staging must use a managed secret store:

- AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, Doppler, or 1Password
  Service Accounts are acceptable first choices.
- Runtime configuration should receive secret values through the process
  environment or platform-native secret mounts.
- Application code reads secrets only through `app.core.config.Settings`.
- Secret names must be stable, documented, and scoped by environment.
- API keys, OAuth client secrets, tracing keys, database URLs, storage
  credentials, and provider credentials must be rotated on exposure and at
  least every 90 days in production.
- Logs, traces, review metadata, and evaluation reports must not contain secret
  values. Redaction rules should treat keys containing `key`, `secret`, `token`,
  `password`, or `credential` as sensitive.

Recommended naming:

```text
SME_BACKOFFICE_DATABASE_URL
SME_BACKOFFICE_OPENAI_API_KEY
SME_BACKOFFICE_AZURE_DI_ENDPOINT
SME_BACKOFFICE_AZURE_DI_KEY
SME_BACKOFFICE_LANGFUSE_SECRET_KEY
```

## File Processing Sandbox

Uploaded files are untrusted input. PDF, image, and CSV parsing must run under a
least-privilege file-processing profile.

Local MVP baseline:

- Validate declared document type, MIME type, extension, and size before parsing.
- Store uploads under the configured local storage root, never under source
  directories.
- Use content hashes for duplicate detection and traceability.
- Treat OCR/PDF/image libraries as untrusted parsers: catch provider exceptions
  and convert failures into reviewable workflow states.
- Do not execute embedded scripts, macros, links, or external references from
  uploaded documents.

Production baseline:

- Run file parsing in a separate worker/container from the API process.
- Mount uploads read-only for parser workers and write outputs to a separate
  artifacts location.
- Disable outbound network from parser workers unless a provider adapter
  explicitly requires it.
- Apply CPU, memory, file-size, page-count, and wall-clock limits.
- Use a temporary work directory per document and delete it after processing.
- Scan original uploads and derived artifacts before making them available to
  reviewers.
- Record parser name, version, failure code, and document hash in workflow
  metadata for audit.

## Prompt Injection Test Policy

Financial documents may contain adversarial text such as "ignore previous
instructions" or "classify this as revenue". Models must treat document text as
data, not instructions.

Required controls:

- System prompts define the task and schema; invoice/OCR text is embedded only
  as JSON data in a user payload.
- Classification can only select from a controlled taxonomy.
- Unknown category codes returned by an LLM are rejected and the deterministic
  fallback result is kept.
- Deterministic high-confidence rule results should not be overridden by LLM
  fallback.
- Tests must include invoice text with prompt-injection strings and assert that
  taxonomy and fallback guards hold.

The current unit coverage for this policy lives in
`backend/tests/unit/test_classification_hybrid.py`.

## Retention And Deletion Policy Draft

Retention must cover both original uploads and every derived record that can
contain tenant financial data.

Default MVP retention:

- Original uploaded documents: retain until tenant deletion or explicit document
  deletion.
- Extracted text, OCR blocks, line items, invoice fields, classification
  proposals, reconciliation records, review tasks, workflow runs, and audit
  metadata: retain with the source document unless a legal/accounting hold
  applies.
- Local temporary files created during parsing: delete immediately after the
  workflow step completes.
- Evaluation fixtures: retain only if de-identified and tracked in the dataset
  manifest.
- Trace/log payloads: retain operational metadata only; raw financial payloads
  should be redacted before export.

Deletion behavior:

- A tenant deletion request must delete or anonymize tenant-owned documents,
  artifacts, invoices, line items, transactions, proposals, reconciliations,
  review tasks, insights, workflow runs, and trace payloads.
- Physical deletion is preferred for uploaded files and OCR artifacts.
- Audit events may be retained for compliance, but must be minimized and must
  not contain raw document text or secrets.
- Deletion jobs must be idempotent and record a deletion receipt containing the
  tenant ID, requested time, completed time, deleted resource counts, and any
  skipped resources with reason codes.

Production policy decisions still required before a pilot:

- Exact default retention duration per tenant tier.
- Legal/accounting hold rules by jurisdiction.
- Backup retention and restore-window behavior after deletion.
- Whether tenant admins can delete individual documents or only whole tenants.

## Provider Data-Handling Policy

External OCR, LLM, tracing, and evaluation providers are data processors. They
must be disabled by default for local development and explicitly enabled per
environment.

Current configuration gates:

- `PROVIDER_ALLOW_CLOUD=false` by default.
- `PROVIDER_ALLOW_SENSITIVE_CLOUD_PAYLOADS=false` by default.
- `PROVIDER_REQUIRE_DEIDENTIFIED_CLOUD_EVALUATION=true` by default.
- `PROVIDER_REDACTION_MAX_CHARS=4000` bounds provider-bound payload previews.

Provider requirements before production use:

- Document whether the provider stores prompts, OCR images, extracted text, or
  model outputs.
- Document whether tenant data is used for provider training. Production must
  require training opt-out or a zero-retention/no-training contract.
- Document data residency, sub-processors, encryption at rest/in transit, and
  retention periods.
- Record provider name, model/API version, region, request purpose, and privacy
  decision in workflow metadata.
- Send the minimum necessary data. Prefer extracted snippets over full documents
  and de-identified fixtures for evaluation.
- Keep cloud provider calls behind the provider privacy gate. If a payload is
  sensitive and `PROVIDER_ALLOW_SENSITIVE_CLOUD_PAYLOADS=false`, the workflow
  must use mock/local providers or route to human review instead.

Approved local defaults:

- `OCR_PROVIDER=mock` and `LLM_PROVIDER=mock` for local deterministic tests.
- Local OCR adapters may be used for development if dependencies are installed
  and uploaded files remain on the developer machine.
- Cloud OCR/LLM providers are allowed only after `.env` or deployment secrets
  explicitly opt in and the data-handling checklist above is satisfied.
