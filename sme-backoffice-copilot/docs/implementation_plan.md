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
- [ ] Add expected extraction labels.
- [ ] Add expected classification labels.
- [ ] Add expected reconciliation labels.
- [ ] Add expected review-routing labels.
- [ ] Implement extraction scorer.
- [ ] Implement statement parsing scorer.
- [ ] Implement classification scorer.
- [ ] Implement reconciliation scorer.
- [ ] Implement insight groundedness scorer.
- [ ] Implement review-routing scorer.
- [ ] Implement workflow replay evaluation.
- [ ] Add evaluation report output.
- [ ] Add evaluation command to README.
- [ ] Decide initial release gates.

## Phase 9 — Real AI provider integration

Goal: connect real AI only after workflow, data, review, and evaluation are
stable.

- [ ] Define AI provider interface.
- [ ] Define OCR provider interface.
- [ ] Define model routing config.
- [ ] Add provider timeout policy.
- [ ] Add provider retry policy.
- [ ] Add provider cost tracking.
- [ ] Add prompt registry.
- [ ] Add structured output validation.
- [ ] Add OpenAI provider adapter or chosen first provider.
- [ ] Add local/Ollama provider adapter if desired.
- [ ] Add NVIDIA NIM provider configuration.
- [ ] Add NVIDIA NIM LLM provider adapter.
- [ ] Add NVIDIA NIM OCR/document parsing provider adapter.
- [ ] Add NVIDIA NIM model routing options for LLM and OCR workloads.
- [ ] Add NVIDIA NIM API key and endpoint environment variables.
- [ ] Add cloud-provider privacy gate before sending financial data externally.
- [ ] Add de-identified-only test policy for cloud provider evaluation.
- [ ] Add provider redaction/minimization policy.
- [ ] Add tests using mock provider.
- [ ] Run evaluation before enabling provider in normal workflow.
- [ ] Compare mock/rule baseline against real provider.
- [ ] Compare local/Ollama baseline against NVIDIA NIM provider outputs.

## Phase 10 — Security and privacy hardening

Goal: make tenant and financial data handling safe by design.

- [ ] Add tenant-scoped repository helpers.
- [ ] Add authorization checks to every tenant resource.
- [ ] Add audit logging for document access.
- [ ] Add audit logging for approval/correction actions.
- [ ] Add audit logging for export/download actions.
- [ ] Redact sensitive payloads from logs.
- [ ] Add secret management convention.
- [ ] Add file processing sandbox strategy.
- [ ] Add prompt-injection test cases.
- [ ] Add cross-tenant access tests.
- [ ] Add retention/deletion policy draft.
- [ ] Add provider data-handling policy documentation.

## Phase 11 — Observability and operations

Goal: make the system debuggable and operable.

- [ ] Add structured logging.
- [ ] Add request correlation IDs.
- [ ] Add workflow correlation IDs.
- [ ] Add agent step metrics.
- [ ] Track latency per endpoint.
- [ ] Track latency per agent.
- [ ] Track cost per model call.
- [ ] Track retry and failure counts.
- [ ] Track review queue size.
- [ ] Track correction rate.
- [ ] Add basic dashboard for local metrics or logs.
- [ ] Define alerting candidates for production.

## Phase 12 — Production readiness

Goal: prepare the MVP for a controlled pilot.

- [ ] Decide target pilot scope.
- [ ] Decide supported invoice formats.
- [ ] Decide supported bank statement formats.
- [ ] Decide supported currencies.
- [ ] Decide supported locales/languages.
- [ ] Define auto-approval thresholds.
- [ ] Define human review policy.
- [ ] Define backup and restore strategy.
- [ ] Define deployment environment strategy.
- [ ] Define database migration process.
- [ ] Define rollback process.
- [ ] Run full test suite.
- [ ] Run full evaluation suite.
- [ ] Review security checklist.
- [ ] Review privacy checklist.
- [ ] Prepare pilot onboarding guide.

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
