# SME Back-Office Copilot — Product Brief

## 1. Business Context

Small and medium-sized enterprises run critical financial operations across
email attachments, PDFs, spreadsheets, bank portals, accounting systems, and
informal approval channels. Owners and finance staff spend substantial time
transcribing documents and reconstructing cash position instead of managing
customers, suppliers, and growth.

The SME Back-Office Copilot is a human-supervised, controlled multi-agent
financial operations platform. Specialized agents convert source documents into
traceable structured records, validate and challenge uncertain outputs, propose
reconciliations and classifications, and present timely operational insights.
It is not an autonomous accountant, payment initiator, statutory filing system,
or source of regulated financial advice.

## 2. SME Pain Points

- Manual invoice entry is slow, repetitive, and error-prone.
- Bank exports vary by institution, format, locale, and statement period.
- Payment-to-invoice matching relies on incomplete references and staff memory.
- Revenue and expense categories are applied inconsistently.
- Cashflow reporting is retrospective and becomes stale quickly.
- Missing documents, duplicate invoices, and overdue receivables are found late.
- Existing tools expose records but rarely explain uncertainty or recommend the
  next operational action.
- SMEs lack dedicated data and AI teams to configure complex automation safely.

## 3. Product Vision

Create a trusted financial operations workspace where an SME can upload source
documents, receive evidence-backed multi-agent automation, resolve only
ambiguous cases, and understand what requires attention each week.

The product follows four principles:

1. **Evidence before assertion:** every extracted field, match, category, and
   insight links back to source evidence.
2. **Confidence-aware automation:** low-confidence or high-impact decisions
   require review.
3. **Reversible actions:** corrections preserve history and improve future
   behavior without erasing prior outputs.
4. **Tenant isolation by design:** customer data, prompts, files, and derived
   records remain scoped to one organization.
5. **Controlled agent autonomy:** agents may propose, validate, retry, and
   explain, but financial-impacting approvals are governed by deterministic
   policy and human review gates.

## 4. User Personas

### Owner-operator

Needs a concise view of cash, overdue payments, unusual spending, and actions for
the coming week. Values speed and plain language over accounting detail.

### Finance administrator or bookkeeper

Uploads documents, resolves exceptions, corrects classifications, and closes
reconciliation periods. Needs batch operations, provenance, and predictable
review queues.

### External accountant

Reviews categorized transactions and supporting evidence across client
organizations. Needs controlled access, audit history, exports, and clear
separation between machine proposals and approved records.

### Operations manager

Tracks supplier payments, customer collections, and recurring costs. Needs
alerts tied to real transactions and invoices rather than generic summaries.

### System administrator

Manages users, retention, integrations, security policy, and usage limits. Needs
tenant-level controls and operational visibility without broad document access.

## 5. User Journey

1. **Onboard:** an organization is created, users receive role-based access, and
   accounting conventions such as currency, timezone, and category taxonomy are
   configured.
2. **Ingest:** a user uploads invoices and bank statements or connects an
   approved source. The system records immutable originals and ingestion
   metadata.
3. **Process:** a controlled multi-agent workflow performs intake, privacy
   scoping, extraction, validation, classification, reconciliation, and review
   routing. Each step records evidence, confidence, validation results, and
   agent/tool versions.
4. **Reconcile:** candidate payment-to-invoice matches are scored. Safe matches
   can be accepted by deterministic policy; ambiguous cases enter a review queue.
5. **Classify:** transactions receive proposed revenue or expense categories,
   with rationale and uncertainty surfaced.
6. **Review:** the user handles exceptions, compares proposals with source
   documents, and approves or corrects results.
7. **Understand:** dashboards update from approved and clearly marked provisional
   records. Weekly insights highlight material changes and recommended actions.
8. **Improve:** corrections become governed evaluation examples and, when
   permitted, tenant-specific signals. They never silently modify global model
   behavior.

## 6. Core Features

### Tier 1 — Operational foundation

#### Invoice Extraction

- Upload PDF and image invoices with duplicate detection and malware scanning.
- Extract supplier, invoice number, dates, currency, totals, tax, line items,
  payment terms, and bank/reference details.
- Store field-level confidence, source location, extractor version, and
  validation errors.
- Route incomplete, conflicting, or policy-sensitive results to human review.

#### Transaction Parsing

- Parse supported CSV, spreadsheet, PDF, and integration-provided statements.
- Normalize dates, amounts, direction, balance, counterparty, and references.
- Preserve the original row or page reference and detect duplicate imports.
- Handle currency, locale, timezone, and debit/credit conventions explicitly.

#### Auto Reconciliation

- Generate candidate matches using deterministic constraints and scored semantic
  signals.
- Support exact, one-to-many, many-to-one, partial, and fee-adjusted proposals.
- Auto-accept only within configurable confidence and amount-risk thresholds.
- Preserve who or what proposed, approved, rejected, or changed each match.

#### Dashboard

- Show current cash position, inflows, outflows, receivables, payables, and
  reconciliation coverage.
- Separate approved, provisional, and unresolved values.
- Support date, account, currency, customer, supplier, and category filters.
- Link every aggregate to contributing records and source evidence.

### Tier 2 — Intelligence and quality

#### Controlled Multi-Agent Workflow

- Coordinate document intake, privacy policy, extraction, validation,
  classification, matching, review, and insight steps as resumable workflows.
- Define an agent registry with bounded responsibilities, allowed tools, input
  contracts, output contracts, retry policy, and escalation behavior.
- Use explicit state, idempotency keys, bounded retries, timeouts, and
  deterministic fallbacks.
- Require human approval at policy-defined confidence or financial impact gates.
- Version prompts, tools, workflow definitions, handoff contracts, and model
  configuration.

#### Insight Generation

- Produce weekly summaries of cash movement, overdue receivables, upcoming
  obligations, spending changes, anomalies, and data-quality gaps.
- Ground every statement in approved records and include calculation windows.
- Prioritize a small number of material, actionable observations.
- Avoid tax, legal, investment, credit, and solvency conclusions unless a future
  regulated product scope explicitly supports them.

#### Evaluation Framework

- Maintain de-identified, consented, versioned datasets representative of target
  document formats and SME segments.
- Measure agent-level extraction accuracy, validation quality, reconciliation
  quality, classification quality, review routing quality, groundedness,
  calibration, latency, cost, and human review burden.
- Run deterministic regression suites in CI and broader model evaluations before
  release.
- Monitor online drift and user corrections without exposing tenant data across
  organizations.

### Tier 3 — Platform scale and governance

#### Model Routing

- Select OCR, document, language, or embedding models by task, sensitivity,
  language, latency, cost, and measured quality.
- Support provider fallback and circuit breaking without changing domain
  contracts.
- Pin model versions for reproducibility and prohibit untested routing changes.

#### Privacy Layer

- Classify sensitive fields and minimize data sent to external processors.
- Redact or tokenize identifiers where task quality permits.
- Enforce tenant-scoped encryption, retention, deletion, consent, and residency
  policy.
- Record model-provider data handling and training opt-out guarantees.

#### Queue Infrastructure

- Move long-running ingestion and workflow steps off synchronous API requests.
- Provide durable delivery, idempotent consumers, retries, dead-letter queues,
  backpressure, and per-tenant fairness.
- Isolate expensive model workloads from interactive dashboard traffic.

#### Observability

- Correlate request, document, workflow, model call, and tenant-safe trace IDs.
- Monitor latency, throughput, failures, queue depth, token usage, cost, quality
  signals, and review rates.
- Keep prompts and financial payloads out of logs by default.
- Alert on service health and quality degradation, not only infrastructure
  failure.

## 7. Success Metrics

Metrics must be segmented by document type, locale, tenant cohort, confidence
band, and model/workflow version.

| Outcome | Initial product target |
|---|---|
| Time saved | At least 60% reduction in median weekly reconciliation effort for pilot SMEs |
| Invoice extraction | At least 95% field-level F1 on required header fields in supported formats |
| Transaction parsing | At least 99.5% exact accuracy for date, amount, and direction on supported digital exports |
| Match quality | At least 98% precision for automatically accepted reconciliations |
| Review routing | At least 95% agreement with approved review policy on labelled workflow cases |
| Review burden | Fewer than 20% of supported records require manual intervention after stabilization |
| Insight trust | At least 95% grounded-claim rate and zero unsupported high-severity recommendations |
| Reliability | 99.9% monthly availability for interactive APIs, excluding announced maintenance |
| Performance | p95 upload acknowledgement under 2 seconds; processing latency tracked separately by document class |
| Adoption | At least 70% of pilot organizations return weekly after onboarding |
| Correction rate | Declining corrections per 100 processed records without reduced coverage |

Targets are launch hypotheses. They become release gates only after baseline
datasets and pilot operating conditions are agreed.

## 8. Risks

| Risk | Consequence | Primary mitigation |
|---|---|---|
| Incorrect extraction or matching | Misstated cash position or missed obligations | Evidence links, confidence gates, deterministic validation, review queues |
| Hallucinated insights | Loss of trust or harmful action | Structured inputs, calculation tools, groundedness checks, restricted claims |
| Over-autonomous agents | Unapproved financial state changes or hard-to-debug behavior | Bounded tool access, persisted handoffs, deterministic approval policy, audit trails |
| Sensitive-data leakage | Regulatory, contractual, and reputational harm | Tenant isolation, encryption, minimization, redaction, provider governance |
| Format and locale variance | Poor coverage outside training examples | Capability matrix, representative evaluations, explicit unsupported states |
| Duplicate or reordered events | Double counting and inconsistent workflow state | Content hashes, idempotency keys, immutable events, transactional state changes |
| Automation bias | Users approve plausible but wrong proposals | Show uncertainty and evidence; require review for high-impact cases |
| Cost or latency spikes | Unviable unit economics and poor experience | Task-specific routing, batching, caching, budgets, asynchronous processing |
| Model/provider drift | Silent quality regression | Version pinning, canaries, evaluation gates, rollback paths |
| Ambiguous regulatory scope | Product used as accounting or financial advice | Clear positioning, jurisdiction review, controlled language and features |
| Weak labelled data governance | Misleading metrics or privacy violations | Dataset lineage, consent, de-identification, access controls, review |

## 9. Future Roadmap

### Phase 0 — Foundation

Establish tenant identity, document storage, audit events, canonical schemas,
security controls, evaluation datasets, initial agent contracts, and local
development infrastructure.

### Phase 1 — Assisted operations

Deliver supported invoice extraction, bank transaction parsing, manual review,
deterministic dashboard calculations, and export. Optimize for traceability over
automation breadth.

### Phase 2 — Controlled multi-agent workflow

Introduce the agent registry, durable graph state, validation loops, candidate
matching, classification proposals, exception queues, approval policy, and
measured auto-acceptance for low-risk cases.

### Phase 3 — Weekly copilot

Release grounded weekly insights, action tracking, notification preferences, and
quality monitoring. Add model routing and durable queues as volume requires.

### Phase 4 — Ecosystem integrations

Connect approved bank feeds, accounting platforms, email ingestion, and supplier
or customer systems. Add API/webhook contracts and partner governance.

### Phase 5 — Advanced finance operations

Explore cashflow forecasting, scenario planning, multi-entity reporting, and
jurisdiction-specific capabilities only after data quality, explainability, and
regulatory requirements are proven.
