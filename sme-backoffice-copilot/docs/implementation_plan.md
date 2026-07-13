# SME Back-Office Copilot — Implementation Plan

Use this file as a living checklist. Tick each item when it is completed:

```md
- [x] Completed task
- [ ] Pending task
```

## Phase 0 — Project foundation

Goal: make the repository easy to run, understand, and extend locally.

- [x] Confirm repository structure matches the intended monorepo layout.
- [x] Confirm backend can start locally.
- [x] Confirm frontend can start locally.
- [x] Confirm Docker Compose can start local dependencies.
- [x] Add `.env.example` values for local development.
- [x] Document local setup steps in `README.md`.
- [x] Confirm all docs are linked from `README.md`.
- [x] Decide minimum supported Python version.
- [x] Decide minimum supported Node.js version.
- [x] Add basic formatting/linting commands.
- [x] Add basic test commands.

## Phase 1 — Core backend skeleton

Goal: create a clean backend foundation without implementing complex business
logic too early.

- [x] Define FastAPI application entrypoint.
- [x] Add health check endpoint.
- [x] Add configuration module.
- [x] Add database connection module.
- [x] Add SQLAlchemy/Alembic setup.
- [x] Add base repository pattern or data-access convention.
- [x] Add API response/error conventions.
- [x] Add request correlation ID middleware.
- [x] Add tenant context placeholder.
- [x] Add authentication placeholder.
- [x] Add authorization policy placeholder.
- [x] Add unit test scaffold.
- [x] Add integration test scaffold.

## Phase 2 — Data model foundation

Goal: represent the important business and workflow concepts before building AI
logic.

- [x] Define `Organization` model.
- [x] Define `User` and `Membership` models.
- [x] Define `Document` model.
- [x] Define `DocumentArtifact` or object reference model.
- [x] Define `ProcessingRun` model.
- [x] Define `WorkflowRun` model.
- [x] Define `AgentDefinition` model.
- [x] Define `AgentStepExecution` model.
- [x] Define `AgentHandoff` model.
- [x] Define `Invoice` model.
- [x] Define `InvoiceLineItem` model.
- [x] Define `InvoiceFieldEvidence` model.
- [x] Define `BankAccount` model.
- [x] Define `StatementImport` model.
- [x] Define `Transaction` model.
- [x] Define `Category` model.
- [x] Define `ClassificationProposal` model.
- [x] Define `Reconciliation` model.
- [x] Define `ReconciliationAllocation` model.
- [x] Define `ReviewTask` model.
- [x] Define `Insight` model.
- [x] Define `AuditEvent` model.
- [x] Add tenant ID to every tenant-owned table.
- [x] Add created/updated timestamps.
- [x] Add immutable versioning strategy for proposals and approvals.
- [x] Add initial Alembic migration.

## Phase 3 — Local document ingestion

Goal: support safe local upload and document tracking.

- [x] Add document upload API endpoint.
- [x] Store uploaded files in local filesystem or local object-storage adapter.
- [x] Compute content hash for uploaded files.
- [x] Detect duplicate documents within a tenant.
- [x] Validate file size.
- [x] Validate MIME type.
- [x] Add placeholder malware scan result.
- [x] Create `DocumentIngested` event or equivalent workflow trigger.
- [x] Add document status lifecycle.
- [x] Add tests for duplicate upload behavior.
- [x] Add tests for unsupported file type behavior.

## Phase 4 — Controlled multi-agent workflow skeleton

Goal: implement the workflow shape before connecting real OCR/LLM providers.

- [x] Define shared workflow state schema.
- [x] Define agent handoff envelope schema.
- [x] Define structured QA error signal schema.
- [x] Define base agent interface.
- [x] Define tool interface convention.
- [x] Implement `Document Intake Agent` skeleton.
- [x] Implement `Privacy & Policy Gate` skeleton.
- [x] Implement `Document Layout Analyzer` skeleton.
- [x] Define invoice extraction group contracts.
- [x] Implement `Metadata Extractor Agent` skeleton.
- [x] Implement `Table Extractor Agent` skeleton.
- [x] Implement `Totals Extractor Agent` skeleton.
- [x] Implement `Invoice Assembly Node` skeleton.
- [x] Implement `QA & Validation Agent` skeleton.
- [x] Implement targeted self-correction routing.
- [x] Implement `Classification Agent` skeleton.
- [x] Implement `Reconciliation Agent` skeleton.
- [x] Implement `Review Coordinator` skeleton.
- [x] Implement `Business Insight Agent` skeleton.
- [x] Persist every agent step execution.
- [x] Persist every handoff.
- [x] Add retry count tracking.
- [x] Add workflow status tracking.
- [x] Add dead-letter/failure state.
- [x] Add workflow replay command for local testing.
- [x] Add tests for successful workflow path.
- [x] Add tests for failed validation path.
- [x] Add tests for retry exhaustion path.

## Phase 5 — Mock-first AI, local-free providers, and deterministic tools

Goal: make the workflow testable without paid external AI APIs, while keeping a
clean path to test with free local models on a developer machine.

### Phase 5.1 — Provider interfaces and local-free adapters

Goal: define stable provider boundaries before wiring agents to real OCR/LLM
implementations.

- [x] Define OCR provider interface.
- [x] Define LLM provider interface.
- [x] Add provider selection configuration.
- [x] Create mock OCR provider.
- [x] Create mock LLM provider.
- [x] Create optional local Tesseract OCR provider adapter.
- [x] Create optional local PaddleOCR provider adapter.
- [x] Create optional local Chandra OCR provider adapter.
- [x] Create optional local Ollama LLM provider adapter.
- [x] Add tests for provider contracts.

### Phase 5.2 — Fixtures and repeatable AI outputs

Goal: provide deterministic invoice and statement examples so tests do not
depend on model randomness.

- [x] Create fixture-based invoice extraction output.
- [x] Create fixture-based statement parsing output.
- [x] Create fixture loader utility.
- [x] Add tests for fixture loading and schema compatibility.

### Phase 5.3 — Deterministic validators

Goal: validate AI outputs with deterministic Python logic instead of trusting
model output blindly.

- [x] Create deterministic arithmetic validator.
- [x] Create deterministic date validator.
- [x] Create deterministic currency validator.
- [x] Create deterministic duplicate detector.
- [x] Add tests for validators.

### Phase 5.4 — Rule-based classification

Goal: classify common SME revenue and expense records without an LLM dependency.

- [x] Create rule-based category classifier.
- [x] Add tests for rule-based classification.

### Phase 5.5 — Deterministic reconciliation

Goal: generate and score invoice-to-transaction match candidates using stable
rules.

- [x] Create deterministic reconciliation candidate generator.
- [x] Create basic match scorer using amount/date/reference.
- [x] Add tests for reconciliation matching.

### Phase 5.6 — Aggregates and grounded insight generation

Goal: compute basic business metrics and produce mock insights grounded in
traceable source data.

- [x] Create deterministic financial aggregate service.
- [x] Create grounded insight mock generator.
- [x] Add tests for financial aggregates.
- [x] Add tests for grounded insight generation.

## Phase 6 — Human review workflow

Goal: make uncertain outputs reviewable instead of pretending AI is always right.

- [x] Define review task types.
- [x] Add API endpoint to list review tasks.
- [x] Add API endpoint to inspect review task details.
- [x] Add API endpoint to approve a proposal.
- [x] Add API endpoint to reject a proposal.
- [x] Add API endpoint to correct extracted fields.
- [x] Add API endpoint to correct classification.
- [x] Add API endpoint to correct reconciliation.
- [x] Record audit events for review actions.
- [x] Supersede old proposals instead of overwriting them.
- [x] Add tests for approval flow.
- [x] Add tests for correction flow.
- [x] Add tests for audit trail behavior.

## Phase 7 — Frontend MVP

Goal: provide a minimal usable interface for upload, review, and dashboard.

- [x] Create application shell layout.
- [x] Create organization selector placeholder.
- [x] Create upload page.
- [x] Show upload status.
- [x] Show document processing status.
- [x] Create review queue page.
- [x] Create review detail page.
- [x] Show source evidence placeholder.
- [x] Add approve/reject/correct actions.
- [x] Create basic dashboard page.
- [x] Show cash position placeholder.
- [x] Show inflow/outflow placeholder.
- [x] Show unresolved item count.
- [x] Show latest insights placeholder.
- [x] Add frontend API client.
- [x] Add frontend loading/error states.

## Phase 8 — Evaluation framework

Goal: make quality measurable before using real AI providers.

- [x] Define labelled dataset manifest format.
- [x] Add sample de-identified invoice fixtures.
- [x] Add sample de-identified statement fixtures.
- [x] Add expected extraction labels.
- [x] Add expected classification labels.
- [x] Add expected reconciliation labels.
- [x] Add expected review-routing labels.
- [x] Implement extraction scorer.
- [x] Implement statement parsing scorer.
- [x] Implement classification scorer.
- [x] Implement reconciliation scorer.
- [x] Implement insight groundedness scorer.
- [x] Implement review-routing scorer.
- [x] Implement workflow replay evaluation.
- [x] Add evaluation report output.
- [x] Add evaluation command to README.
- [x] Decide initial release gates.

## Phase 9 — Real AI provider integration

Goal: connect real AI only after workflow, data, review, and evaluation are
stable.

- [x] Define AI provider interface.
- [x] Define OCR provider interface.
- [x] Define model routing config.
- [x] Add provider timeout policy.
- [x] Add provider retry policy.
- [x] Add provider cost tracking.
- [x] Add prompt registry.
- [x] Add structured output validation.
- [x] Add OpenAI provider adapter or chosen first provider.
- [x] Add local/Ollama provider adapter if desired.
- [ ] Add NVIDIA NIM provider configuration.
- [ ] Add NVIDIA NIM LLM provider adapter.
- [ ] Add NVIDIA NIM OCR/document parsing provider adapter.
- [ ] Add NVIDIA NIM model routing options for LLM and OCR workloads.
- [ ] Add NVIDIA NIM API key and endpoint environment variables.
- [x] Add cloud-provider privacy gate before sending financial data externally.
- [x] Add de-identified-only test policy for cloud provider evaluation.
- [x] Add provider redaction/minimization policy.
- [x] Add tests using mock provider.
- [ ] Run evaluation before enabling provider in normal workflow.
- [ ] Compare mock/rule baseline against real provider.
- [ ] Compare local/Ollama baseline against NVIDIA NIM provider outputs.

## Phase 9.5 — Provider-backed end-to-end workflow wiring

Goal: connect document upload, workflow orchestration, selected OCR/LLM
providers, AI extraction proposals, and human review into one local end-to-end
path.

- [x] Build provider factory from settings.
- [x] Build provider routing factory from settings.
- [x] Wire selected OCR provider into document workflow.
- [x] Wire selected LLM provider into invoice extraction workflow.
- [x] Trigger workflow from `DocumentIngested` event.
- [x] Convert OCR output into workflow state.
- [x] Convert LLM output into invoice extraction group contracts.
- [x] Persist extracted invoice proposal.
- [x] Create review task from extracted invoice proposal.
- [x] Show generated review task in frontend review queue.
- [x] Add local upload-to-review smoke test with mock providers.
- [x] Add local upload-to-review smoke test with Ollama provider.
- [x] Add failure path when provider output fails validation.
- [x] Add fallback to review-required state when provider fails.

## Phase 9.5B — Layout-aware invoice extraction hardening

Goal: reduce case-specific parser heuristics by preserving OCR layout, detecting
document regions, and giving extractor agents structured page context instead
of only flattened OCR text.

- [x] Preserve OCR text blocks and bounding boxes from PaddleOCR provider output.
- [x] Normalize OCR provider output into common layout blocks.
- [x] Store OCR layout blocks in shared workflow state.
- [x] Store OCR layout diagnostics in workflow metadata.
- [x] Define document region contracts for header, supplier, bill-to, ship-to, line-item table, totals, and footer.
- [x] Implement OCR block grouping into page regions.
- [x] Implement layout-aware party role detection.
- [x] Implement layout-aware totals region detection.
- [x] Pass layout regions to metadata/table/totals extractor agents.
- [x] Prefer region-aware extraction over plain-text fallback.
- [x] Keep deterministic fallback as a safety net instead of the primary extractor.
- [x] Add regression invoice fixtures for multi-column invoices.
- [x] Add receipt-style invoice regression fixture.
- [x] Add `Bill No.` / `Receipt No.` invoice-number extraction rule.
- [x] Add locale-aware date parsing for `DD/MM/YY` receipts.
- [x] Add subtotal-vs-line-items QA validator.
- [x] Route subtotal mismatch to human review with structured QA error signal.
- [x] Add angled-photo invoice regression fixture.
- [x] Add supplier detection from top-left sender block.
- [x] Add multi-line line-item description grouping.
- [x] Add UK/EU date ambiguity handling for `DD/MM/YYYY` vs `MM/DD/YYYY`.
- [x] Add discount/VAT/total arithmetic validator.
- [x] Flag schema-valid but financially-incomplete extraction as review-required.
- [x] Add validation rules for party-role confusion.
- [x] Add evaluation cases for layout-heavy invoices.

## Phase 9.6 — Agent orchestration and tracing observability

Goal: evolve the custom workflow runtime into a graph-based multi-agent
orchestration layer, while making every OCR, LLM, validator, retry, handoff, and
human-review routing decision traceable without leaking sensitive financial
data.

- [x] Decide LangGraph adoption scope.
- [x] Add LangGraph dependency and local configuration.
- [x] Create LangGraph workflow adapter behind existing workflow contracts.
- [x] Convert current document preparation steps into LangGraph nodes.
- [x] Convert invoice metadata/table/totals extractors into LangGraph nodes.
- [x] Convert invoice assembly and QA validation into LangGraph nodes.
- [x] Add conditional QA routing edge for valid, retry, review-required, and failed paths.
- [x] Add targeted self-correction loop in LangGraph.
- [x] Add retry exhaustion path in LangGraph.
- [x] Preserve existing workflow persistence for agent step executions.
- [x] Preserve existing handoff persistence from graph node transitions.
- [x] Add checkpoint/replay support for local graph runs.
- [x] Add tracing provider interface for Langfuse or LangSmith.
- [x] Choose first tracing backend: Langfuse local/self-host or LangSmith cloud.
- [x] Add tracing provider configuration.
- [x] Add redaction/minimization before sending trace payloads externally.
- [x] Trace OCR provider calls.
- [x] Trace LLM provider calls.
- [x] Trace deterministic validators.
- [x] Trace QA error signals and correction routing.
- [x] Trace review-task creation.
- [x] Add local trace/debug command for one uploaded document.
- [x] Add tests for LangGraph happy path.
- [x] Add tests for LangGraph validation retry path.
- [x] Add tests for LangGraph retry exhaustion path.
- [x] Add tests proving sensitive fields are redacted from trace payloads.
- [x] Document LangGraph and tracing workflow in README.

## Phase 10 — Security and privacy hardening

Goal: make tenant and financial data handling safe by design.

- [x] Add tenant-scoped repository helpers.
- [x] Add authorization checks to every tenant resource.
- [x] Add audit logging for document access.
- [x] Add audit logging for approval/correction actions.
- [x] Add audit logging for export/download actions.
- [x] Redact sensitive payloads from logs.
- [x] Add secret management convention.
- [x] Add file processing sandbox strategy.
- [x] Add prompt-injection test cases.
- [x] Add cross-tenant access tests.
- [x] Add retention/deletion policy draft.
- [x] Add provider data-handling policy documentation.

## Phase 10.5 — Post-extraction integration (Classification & Reconciliation)

Goal: replace skeleton placeholders with the actual rule-based category classifier and deterministic reconciliation match engines.

- [x] Connect the `rule_based_category_classifier` tool to the `ClassificationAgent` to perform actual classification.
- [x] Connect the `deterministic_match_scorer` and candidate generator to the `ReconciliationAgent`.
- [x] Wire database queries in the `ReconciliationAgent` to retrieve transaction candidates dynamically for the tenant.
- [x] Add end-to-end integration tests for the real classification and reconciliation execution in the LangGraph workflow.
- [x] Verify that live classification and reconciliation results display correctly in the human review queue UI.

## Phase 11 — Observability and operations

Goal: make the system debuggable and operable.

- [x] Add structured logging.
- [x] Add request correlation IDs.
- [x] Add workflow correlation IDs.
- [x] Add agent step metrics.
- [x] Track latency per endpoint.
- [x] Track latency per agent.
- [x] Track cost per model call.
- [x] Track retry and failure counts.
- [x] Track review queue size.
- [x] Track correction rate.
- [x] Add basic dashboard for local metrics or logs.
- [x] Define alerting candidates for production.

## Phase 12 — Production readiness

Goal: prepare the MVP for a controlled pilot.

- [x] Decide target pilot scope.
- [x] Decide supported invoice formats.
- [x] Decide supported bank statement formats.
- [x] Decide supported currencies.
- [x] Decide supported locales/languages.
- [x] Define auto-approval thresholds.
- [x] Define human review policy.
- [x] Define backup and restore strategy.
- [x] Define deployment environment strategy.
- [x] Define database migration process.
- [x] Define rollback process.
- [x] Run full test suite.
- [x] Run full evaluation suite.
- [x] Review security checklist.
- [x] Review privacy checklist.
- [x] Prepare pilot onboarding guide.

## Phase 13 — Async job queue and worker runtime

Goal: decouple workflow execution from the HTTP request lifecycle through an application-level queue abstraction, allowing interchangeable in-process and distributed worker runtimes.

Boundary principle: API and application services publish workflow jobs through a queue interface; Celery/Redis stays an infrastructure adapter behind that boundary.

### Phase 13.1 — Queue abstraction

Goal: define the application boundary for background workflow execution without coupling the core app to Celery or any specific broker.

- [x] Define `DocumentProcessingCommand` and `JobRef` contracts.
- [x] Define `WorkflowJobQueue` protocol as the application boundary.
- [x] Keep API/application services free of direct Celery imports; use the queue boundary only.
- [x] Add in-process queue adapter for local/dev fallback.
- [x] Move document upload workflow trigger to publish a background job instead of running workflow inline.
- [x] Keep upload API fast: persist document, create queued workflow run, enqueue job, return response.
- [x] Add `queued`, `running`, `succeeded`, `failed`, `retrying`, `cancelled`, and `lost` workflow/job status handling.
- [x] Add progress reporting for workflow phases such as OCR, extraction, QA, classification, reconciliation, and insights.
- [x] Add job cancellation contract so queued jobs can be cancelled before a worker starts them.

### Phase 13.2 — Celery infrastructure

Goal: implement the distributed worker runtime as an infrastructure adapter behind the queue boundary.

- [x] Add Celery/Redis queue adapter behind the `WorkflowJobQueue` boundary.
- [x] Add Celery app factory and worker entrypoint.
- [x] Add document-processing Celery task that loads command payloads and runs the workflow.
- [x] Add Redis service and worker command to Docker Compose.
- [x] Add configuration for queue mode, broker URL, result backend, concurrency, and retry limits.
- [x] Add priority queue support for high, medium, and low priority workflow jobs.
- [x] Add worker-side provider rate limiting for OCR and LLM calls.
- [x] Document worker scaling model by job type, such as OCR-heavy, LLM-heavy, and review-coordination work.

### Phase 13.3 — Reliability

Goal: make queued workflow execution safe to retry, trace, observe, and operate in a production pilot.

- [x] Persist document, workflow run, durable job, and outbox event in one database transaction.
- [x] Dispatch committed outbox events to the selected queue with exponential publish retry.
- [x] Add idempotency key based on workflow run ID.
- [x] Add duplicate job handling so replay/retry does not create duplicate invoices/review tasks.
- [x] Add worker correlation IDs and workflow correlation IDs across API -> queue -> worker.
- [x] Add queue metrics: enqueued, started, succeeded, failed, retried, queue latency.
- [x] Add retry policy with exponential backoff and terminal dead-letter/failure state.
- [x] Add worker heartbeat and `last_seen_at` tracking.
- [x] Mark stale running jobs as failed or lost after the configured heartbeat timeout.
- [x] Add dead-letter handling for terminal workflow failures.
- [x] Add tests for API enqueue behavior.
- [x] Add tests for in-process queue adapter.
- [x] Add tests for Celery adapter task payload construction without requiring a live broker.
- [x] Add tests for idempotent duplicate job handling.
- [x] Add tests for cancellation, progress updates, heartbeat timeout, and priority routing.
- [x] Document local worker startup, queue modes, outbox recovery, and scaling model.
- [ ] Split the monolithic document task into independently scalable OCR and LLM stage tasks when production load justifies the added orchestration complexity.

## Phase 14 — Public pilot deployment

Goal: deploy a secure, observable public pilot without changing the application
boundary between HTTP, queue, worker, database, and document storage.

Target architecture:

```text
Browser
  -> Vercel (Next.js frontend)
  -> Azure Container Apps (FastAPI API)
       -> Neon PostgreSQL
       -> Upstash Redis
       -> Azure Blob Storage (private documents)
       -> Azure AI Document Intelligence

Azure Container Apps (Celery worker)
Azure Container Apps (outbox dispatcher)
```

Keep the API, Celery worker, and outbox dispatcher as independently deployed
processes. They use the same image, but each has its own command, health
policy, scaling configuration, and environment variables.

### Phase 14.1 — Deployment foundation

Goal: define the public environments and prepare deployment-safe configuration.

- [x] Create an Azure resource group and choose one pilot region close to pilot users.
- [ ] Create separate `staging` and `production` environments; do not use local credentials in either.
- [ ] Create a dedicated Azure service principal or managed identity for deployment automation.
- [x] Create Azure Blob Storage with a private container for original documents and derived artifacts.
- [x] Add an `AzureBlobStorage` adapter behind the existing document-storage boundary.
- [x] Store only document metadata, content hashes, and Blob object keys in PostgreSQL; do not store file bytes in database rows.
- [ ] Configure lifecycle rules for document retention and deletion according to `docs/security_privacy.md`.
- [x] Decide initial managed-service split: Neon PostgreSQL, Upstash Redis, Azure Blob Storage, Azure Document Intelligence, and Azure Container Apps.
- [x] Document all required environment variables in `.env.example` without committing any secret values.

### Phase 14.2 — Container workloads

Goal: run each runtime role independently in Azure Container Apps.

- [ ] Build and publish the backend image to Azure Container Registry or GitHub Container Registry.
- [ ] Deploy FastAPI as the public Container App with HTTPS ingress and a `/health` endpoint.
- [ ] Deploy Celery worker as a private Container App with no public ingress.
- [ ] Deploy outbox dispatcher as a private Container App with no public ingress.
- [ ] Configure `QUEUE_MODE=celery` for deployed API and dispatcher processes.
- [ ] Configure Celery worker queue routing and priority queues: `high`, `medium`, `low`.
- [ ] Configure worker concurrency conservatively for OCR/LLM provider quotas, then tune from ops metrics.
- [ ] Add liveness/readiness checks for API, worker heartbeat, and outbox dispatcher.
- [ ] Configure minimum replicas appropriate for the pilot so workers do not sleep while queued work exists.
- [ ] Verify API, worker, and outbox dispatcher can be restarted independently without losing committed jobs.

### Phase 14.3 — Security, secrets, and networking

Goal: make public access narrow, private data encrypted, and credentials replaceable.

- [ ] Put runtime secrets in Azure Key Vault or the Container Apps secret store; never place secrets in Docker images, source code, or frontend variables.
- [ ] Grant the API/worker identity least-privilege access to Blob Storage and Key Vault.
- [ ] Use private Blob containers and short-lived server-generated access URLs when a browser must retrieve a document.
- [ ] Restrict CORS to the deployed Vercel domain and staging domain.
- [ ] Set `APP_ENV`, `APP_DEBUG=false`, trusted frontend origins, and production log level explicitly.
- [ ] Enable TLS for every public endpoint and use TLS connection strings for Neon and Upstash.
- [ ] Configure provider keys for Azure Document Intelligence and the selected LLM without logging their values.
- [ ] Verify production logs redact invoice fields, provider payloads, authorization headers, and secrets.
- [ ] Configure API, Celery worker, and outbox dispatcher with Neon pooled PostgreSQL connection strings.
- [ ] Reserve the Neon direct PostgreSQL connection string for Alembic migrations and explicit administrative operations only.
- [ ] Set bounded SQLAlchemy pool size and max overflow per runtime role so API, worker, and dispatcher cannot exhaust Neon connection limits collectively.
- [ ] Configure Celery broker, result backend when enabled, and Redis provider-rate-limit client with Upstash `rediss://` TLS URLs.
- [ ] Reject non-TLS Redis URLs outside explicitly local development configuration.
- [ ] Verify hosted PostgreSQL and Redis connections negotiate TLS during the public smoke test.

### Phase 14.4 — Frontend and delivery pipeline

Goal: deploy a reproducible frontend and backend from reviewed source changes.

- [ ] Deploy Next.js frontend to Vercel.
- [ ] Configure Vercel environment variables with the public API base URL only; do not expose backend/provider secrets.
- [ ] Add a GitHub Actions workflow that runs backend tests, frontend checks, and image build before deployment.
- [ ] Deploy automatically to staging from the integration branch.
- [ ] Require manual approval for production deployment.
- [ ] Run database migrations as an explicit release step before new worker/API code starts.
- [ ] Record deployed image tag, migration revision, and frontend deployment URL in release notes.
- [ ] Define rollback: redeploy prior image tag, then use backward-compatible migrations or a documented database restore procedure.

### Phase 14.5 — Public smoke test and pilot handoff

Goal: prove the deployed system works end-to-end before inviting pilot users.

- [ ] Run migration against the hosted PostgreSQL database.
- [ ] Confirm API health endpoint and frontend API connectivity.
- [ ] Upload one invoice and confirm the HTTP request returns before OCR/LLM workflow completes.
- [ ] Confirm Blob object upload, durable outbox delivery, Celery execution, workflow progress, and review task creation.
- [ ] Approve/correct a review task and verify classification/reconciliation continuation.
- [ ] Upload a matching bank CSV and verify reconciliation output.
- [ ] Intentionally restart a worker during a workflow and verify heartbeat recovery, retry, or terminal failure behavior.
- [ ] Intentionally make Redis unavailable briefly and verify committed outbox events are later dispatched.
- [ ] Verify Ops dashboard shows endpoint latency, provider failures, queue depth, queue latency, retry counts, and correction rate.
- [ ] Capture public-pilot screenshots and a short demo recording for the presentation.
- [ ] Create a pilot operator runbook: incident triage, replay/cancel workflow, retry dead-letter job, data deletion request, and rollback.

## Nice-to-have later

- [ ] Add email ingestion.
- [ ] Add bank feed integration.
- [ ] Add accounting system export.
- [ ] Add webhook API.
- [ ] Add multi-entity reporting.
- [ ] Add cashflow forecasting.
- [ ] Add scenario planning.
- [ ] Add advanced anomaly detection.
- [ ] Add tenant-specific learning signals.
- [ ] Add production-grade vector search.
