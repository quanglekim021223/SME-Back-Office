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
- [ ] Add database connection module.
- [ ] Add SQLAlchemy/Alembic setup.
- [ ] Add base repository pattern or data-access convention.
- [ ] Add API response/error conventions.
- [ ] Add request correlation ID middleware.
- [ ] Add tenant context placeholder.
- [ ] Add authentication placeholder.
- [ ] Add authorization policy placeholder.
- [ ] Add unit test scaffold.
- [ ] Add integration test scaffold.

## Phase 2 — Data model foundation

Goal: represent the important business and workflow concepts before building AI
logic.

- [ ] Define `Organization` model.
- [ ] Define `User` and `Membership` models.
- [ ] Define `Document` model.
- [ ] Define `DocumentArtifact` or object reference model.
- [ ] Define `ProcessingRun` model.
- [ ] Define `WorkflowRun` model.
- [ ] Define `AgentDefinition` model.
- [ ] Define `AgentStepExecution` model.
- [ ] Define `AgentHandoff` model.
- [ ] Define `Invoice` model.
- [ ] Define `InvoiceLineItem` model.
- [ ] Define `InvoiceFieldEvidence` model.
- [ ] Define `BankAccount` model.
- [ ] Define `StatementImport` model.
- [ ] Define `Transaction` model.
- [ ] Define `Category` model.
- [ ] Define `ClassificationProposal` model.
- [ ] Define `Reconciliation` model.
- [ ] Define `ReconciliationAllocation` model.
- [ ] Define `ReviewTask` model.
- [ ] Define `Insight` model.
- [ ] Define `AuditEvent` model.
- [ ] Add tenant ID to every tenant-owned table.
- [ ] Add created/updated timestamps.
- [ ] Add immutable versioning strategy for proposals and approvals.
- [ ] Add initial Alembic migration.

## Phase 3 — Local document ingestion

Goal: support safe local upload and document tracking.

- [ ] Add document upload API endpoint.
- [ ] Store uploaded files in local filesystem or local object-storage adapter.
- [ ] Compute content hash for uploaded files.
- [ ] Detect duplicate documents within a tenant.
- [ ] Validate file size.
- [ ] Validate MIME type.
- [ ] Add placeholder malware scan result.
- [ ] Create `DocumentIngested` event or equivalent workflow trigger.
- [ ] Add document status lifecycle.
- [ ] Add tests for duplicate upload behavior.
- [ ] Add tests for unsupported file type behavior.

## Phase 4 — Controlled multi-agent workflow skeleton

Goal: implement the workflow shape before connecting real OCR/LLM providers.

- [ ] Define shared workflow state schema.
- [ ] Define agent handoff envelope schema.
- [ ] Define structured QA error signal schema.
- [ ] Define base agent interface.
- [ ] Define tool interface convention.
- [ ] Implement `Document Intake Agent` skeleton.
- [ ] Implement `Privacy & Policy Gate` skeleton.
- [ ] Implement `Document Layout Analyzer` skeleton.
- [ ] Define invoice extraction group contracts.
- [ ] Implement `Metadata Extractor Agent` skeleton.
- [ ] Implement `Table Extractor Agent` skeleton.
- [ ] Implement `Totals Extractor Agent` skeleton.
- [ ] Implement `Invoice Assembly Node` skeleton.
- [ ] Implement `QA & Validation Agent` skeleton.
- [ ] Implement targeted self-correction routing.
- [ ] Implement `Classification Agent` skeleton.
- [ ] Implement `Reconciliation Agent` skeleton.
- [ ] Implement `Review Coordinator` skeleton.
- [ ] Implement `Business Insight Agent` skeleton.
- [ ] Persist every agent step execution.
- [ ] Persist every handoff.
- [ ] Add retry count tracking.
- [ ] Add workflow status tracking.
- [ ] Add dead-letter/failure state.
- [ ] Add workflow replay command for local testing.
- [ ] Add tests for successful workflow path.
- [ ] Add tests for failed validation path.
- [ ] Add tests for retry exhaustion path.

## Phase 5 — Mock-first AI and deterministic tools

Goal: build the system without paying for external AI APIs yet.

- [ ] Create mock OCR provider.
- [ ] Create mock LLM provider.
- [ ] Create fixture-based invoice extraction output.
- [ ] Create fixture-based statement parsing output.
- [ ] Create deterministic arithmetic validator.
- [ ] Create deterministic date validator.
- [ ] Create deterministic currency validator.
- [ ] Create deterministic duplicate detector.
- [ ] Create rule-based category classifier.
- [ ] Create deterministic reconciliation candidate generator.
- [ ] Create basic match scorer using amount/date/reference.
- [ ] Create deterministic financial aggregate service.
- [ ] Create grounded insight mock generator.
- [ ] Add tests for validators.
- [ ] Add tests for rule-based classification.
- [ ] Add tests for reconciliation matching.

## Phase 6 — Human review workflow

Goal: make uncertain outputs reviewable instead of pretending AI is always right.

- [ ] Define review task types.
- [ ] Add API endpoint to list review tasks.
- [ ] Add API endpoint to inspect review task details.
- [ ] Add API endpoint to approve a proposal.
- [ ] Add API endpoint to reject a proposal.
- [ ] Add API endpoint to correct extracted fields.
- [ ] Add API endpoint to correct classification.
- [ ] Add API endpoint to correct reconciliation.
- [ ] Record audit events for review actions.
- [ ] Supersede old proposals instead of overwriting them.
- [ ] Add tests for approval flow.
- [ ] Add tests for correction flow.
- [ ] Add tests for audit trail behavior.

## Phase 7 — Frontend MVP

Goal: provide a minimal usable interface for upload, review, and dashboard.

- [ ] Create application shell layout.
- [ ] Create organization selector placeholder.
- [ ] Create upload page.
- [ ] Show upload status.
- [ ] Show document processing status.
- [ ] Create review queue page.
- [ ] Create review detail page.
- [ ] Show source evidence placeholder.
- [ ] Add approve/reject/correct actions.
- [ ] Create basic dashboard page.
- [ ] Show cash position placeholder.
- [ ] Show inflow/outflow placeholder.
- [ ] Show unresolved item count.
- [ ] Show latest insights placeholder.
- [ ] Add frontend API client.
- [ ] Add frontend loading/error states.

## Phase 8 — Evaluation framework

Goal: make quality measurable before using real AI providers.

- [ ] Define labelled dataset manifest format.
- [ ] Add sample de-identified invoice fixtures.
- [ ] Add sample de-identified statement fixtures.
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
- [ ] Add provider redaction/minimization policy.
- [ ] Add tests using mock provider.
- [ ] Run evaluation before enabling provider in normal workflow.
- [ ] Compare mock/rule baseline against real provider.

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
