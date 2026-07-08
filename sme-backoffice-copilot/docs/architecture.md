# SME Back-Office Copilot — Architecture

## 1. Architectural Goals

The architecture is a **controlled multi-agent financial operations platform**.
It uses specialized agents for document intake, extraction, validation,
classification, reconciliation, insight generation, and review coordination, but
keeps autonomy bounded by deterministic policy, durable workflow state, typed
contracts, human review, and evaluation gates.

The platform is intentionally not an autonomous accountant, payment initiator,
tax filing system, or source of regulated financial advice.

Key quality attributes are:

- **Traceability:** every derived value links to source evidence and processing
  versions.
- **Bounded autonomy:** agents may propose, validate, route, and explain; policy
  decides financial-impacting state transitions.
- **Idempotency:** uploads, jobs, events, and state transitions tolerate retries.
- **Tenant isolation:** tenant boundaries apply to storage, queries, queues,
  caches, prompts, telemetry, and model calls.
- **Human control:** low-confidence, high-impact, or policy-sensitive outcomes
  require review.
- **Evolvability:** models, prompts, tools, workflows, and storage choices are
  replaceable behind versioned contracts.

See [agent_architecture.md](agent_architecture.md) for the detailed agent
registry, handoff protocol, state model, and agent-specific governance rules.

## 2. High-Level Architecture

```text
┌──────────────────────────── User / External Systems ───────────────────────────┐
│ Browser UI       Mobile browser       Accounting/Bank connectors (future)      │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ HTTPS / OAuth / Webhooks
                                v
┌──────────────────────── Presentation Layer ────────────────────────────────────┐
│ Next.js web app     Upload/review/dashboard UX     Tenant-safe API client      │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Versioned REST API
                                v
┌──────────────────────── Application Layer ─────────────────────────────────────┐
│ FastAPI routes  AuthN/AuthZ  Tenant policy  Use cases  Review/query services   │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Commands / queries / durable job requests
                                v
┌──────────────────────── Multi-Agent Workflow Layer ────────────────────────────┐
│ Durable graph orchestration  Checkpoints  Handoffs  Retries  Human gates       │
│ Intake → Policy → Extraction → QA → Classification → Reconciliation → Review   │
│                                                        ↓                       │
│                                                   Insight Agent                │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Typed tool/service interfaces
                                v
┌────────────────────────── AI and Tool Service Layer ───────────────────────────┐
│ OCR/document AI  LLM gateway  Embeddings  Model router  Rule engines           │
│ Validators  Financial calculators  Grounding checks  Safety/privacy filters    │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Repositories / object access / events
                                v
┌──────────────────────────── Data Layer ────────────────────────────────────────┐
│ PostgreSQL: canonical records, proposals, workflow state, audit, provenance    │
│ Object storage: immutable originals and derived artifacts                      │
│ Search/vector/read models: introduced only behind tenant-scoped contracts      │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Managed runtime capabilities
                                v
┌──────────────────────── Infrastructure Layer ──────────────────────────────────┐
│ Containers  Queue  Secrets/KMS  IAM  Network  Logs/metrics/traces  CI/CD       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Cross-cutting controls—tenant isolation, encryption, audit, schema versioning,
idempotency, observability, evaluation, and rollback—apply to every layer.

## 3. Layered Architecture

The dependency direction is downward. Lower layers must not import presentation
or workflow concerns. Upward communication occurs through return contracts,
events, and persisted state transitions.

```text
Presentation Layer
        ↓
Application Layer
        ↓
Multi-Agent Workflow Layer
        ↓
AI and Tool Service Layer
        ↓
Data Layer
        ↓
Infrastructure Layer
```

### Presentation Layer

Owns navigation, rendering, browser-side interaction, accessible review tools,
upload progress, and dashboard visualizations. It consumes versioned APIs and
never accesses databases, object stores, queues, or model providers directly.
Sensitive data should be held in browser state only as long as the interaction
requires.

### Application Layer

Owns transport-neutral use cases, API contracts, authentication integration,
tenant authorization, validation, rate limits, review commands, dashboard
queries, and transaction boundaries. Routes remain thin: they parse and validate
requests, invoke one application capability, and map typed results to responses.

This layer distinguishes synchronous work from accepted asynchronous work. An
upload request should durably store metadata and return a job identifier; it
should not hold an HTTP connection open for model processing.

### Multi-Agent Workflow Layer

Owns long-running and multi-step control flow. It coordinates specialized agents
through explicit handoff contracts and durable state. Each agent has a bounded
responsibility, allowed tools, input schema, output schema, retry policy,
confidence policy, and escalation path.

This layer records workflow state, agent inputs and outputs, model/prompt/tool
versions, retry counts, validation results, confidence values, and human-review
status. Each step is idempotent and resumable.

Agent autonomy is intentionally limited:

- agents produce proposals, validations, explanations, and routing
  recommendations;
- deterministic policy decides auto-approval eligibility;
- high-impact or uncertain results become review tasks;
- agents cannot bypass tenant authorization, mutate canonical records directly,
  or call unapproved tools.

### AI and Tool Service Layer

Owns adapters for OCR, document understanding, language models, embeddings,
classification tools, rule engines, financial calculators, validators, and
grounding checks. A model gateway enforces structured output schemas, timeouts,
provider policy, content minimization, version capture, token/cost budgets,
retry rules, and telemetry.

Provider responses are proposals, never canonical records. Validation and
grounding occur before outputs cross into workflow state. Routing decisions use
evaluation evidence and task policy, not ad hoc calls from feature code.

### Data Layer

Owns repositories, persistence mappings, canonical record rules, object access,
provenance, audit events, workflow state, agent outputs, and query models.
PostgreSQL is the initial system of record for transactional metadata. Object
storage holds immutable uploads and derived page images or text. Binary
documents should not be stored in relational rows.

Canonical records, machine proposals, user approvals, agent step outputs, and
superseded versions remain distinct. Tenant ID is mandatory on every tenant-owned
record and is enforced through repository scoping and, where supported, database
row-level security.

### Infrastructure Layer

Owns compute, networking, queueing, managed databases, object storage, secrets,
key management, deployment, backups, disaster recovery, monitoring, and CI/CD.
Local Docker Compose mirrors service boundaries but is not a production topology.
Application code depends on capability interfaces, allowing local and cloud
implementations to differ.

## 4. Multi-Agent Data Flow

```text
Upload Invoice / Statement
      │
      v
Document Intake Agent
      │ accepted metadata + content hash + document type
      v
Privacy & Policy Gate
      │ allowed processing scope + redaction/minimization rules
      v
Document Layout Analyzer
      │ region plan + OCR/layout artifacts
      v
┌──────────────────────┬──────────────────────┬──────────────────────┐
│ Metadata Extractor   │ Table Extractor       │ Totals Extractor      │
│ Agent                │ Agent                 │ Agent                 │
└──────────┬───────────┴──────────┬───────────┴──────────┬───────────┘
           │ Group 1 metadata      │ Group 2 line items    │ Group 3 totals
           └───────────────────────┴──────────┬───────────┘
                                              v
Invoice Assembly Node
      │ proposed invoice payload + grouped evidence + confidence
      v
QA & Validation Agent
      │ valid ───────────────┐
      │ invalid              │
      v                      v
Targeted retry / Review / DLQ   Classification Agent
                             │ proposed category + rationale
                             v
                       Reconciliation Agent
                             │ ranked match proposals
                             v
                       Review Coordinator
                         │           │
                   auto-approve   human review
                         │           │
                         v           v
                      Dashboard ← Approved / corrected records
                         │
                         v
                    Business Insight Agent
                         │ grounded weekly insights
                         v
                      Dashboard / Notifications
```

### Step 1 — Upload and intake

1. The frontend requests an upload session.
2. The application layer authenticates the user, authorizes the organization,
   validates file metadata, and creates a document record plus idempotency key.
3. Prefer direct upload to tenant-scoped object storage using a short-lived
   signed URL. The backend records the content hash, size, media type, and object
   version after upload.
4. The Document Intake Agent verifies file type, duplicate identity, malware scan
   result, ingestion metadata, and processing eligibility.
5. A durable `DocumentIngested` event starts the workflow. The API returns a job
   ID that the UI can poll or subscribe to.

### Step 2 — Privacy and policy gate

1. Tenant policy determines whether the document may be processed, which tools
   are allowed, and whether external model providers may receive any content.
2. Sensitive fields are minimized, redacted, or tokenized where task quality
   permits.
3. The workflow records the allowed processing scope before any model call.

### Step 3 — Layout analysis and grouped extraction

1. The workflow renders or normalizes the source without changing the original.
2. The Document Layout Analyzer identifies regions for metadata, line-item
   tables, totals/formulas, and unsupported or low-quality areas.
3. Invoice extraction is split into focused sub-agents:

   - Metadata Extractor Agent for supplier, buyer, tax IDs, invoice number,
     dates, currency, and payment terms.
   - Table Extractor Agent for line items, quantities, unit prices, tax rates,
     discounts, and line amounts.
   - Totals Extractor Agent for subtotal, tax, fees, discounts, total, and
     amount in words.
4. **Fast-Path & Adaptive Field-Level Fallback (Optimized)**:
   - When configured with a structured extraction provider (e.g., Azure Document Intelligence `prebuilt-invoice` model), the system pre-populates `state.scratchpad` with structured data.
   - If the pre-populated group data exists with high confidence, the respective extraction agent skips the LLM call entirely, reducing latency to milliseconds.
   - **Financial Plausibility Check**: Before saving, the structured parser runs a deterministic sanity check (e.g., asserting `total_amount >= subtotal_amount`). If violated (e.g., due to a stamp obscuring the total), the group's confidence is downgraded to `"low"`, forcing that specific agent to fallback to LLM processing while others remain on the fast-path.
5. The Invoice Assembly Node merges the grouped outputs into one invoice
   proposal without inventing fields.
6. Each group stores source evidence, confidence, model/prompt/configuration
   versions, and region references. Output is treated as a proposal, not truth.


### Step 4 — QA & Validation Agent

1. The agent checks schema validity, arithmetic consistency, date logic,
   currency rules, duplicate identity, source grounding, and required fields.
2. If the result is repairable, it emits a structured error signal with
   `error_code`, `target_agent`, `target_field`, observed values, expected
   values, and a short repair instruction.
3. Repair signals are routed to the smallest responsible component: metadata,
   table, totals, or assembly. The workflow should not retry full invoice
   extraction when one bounded region is responsible.
4. Retries are capped. Repeated failure routes the item to human review or a
   dead-letter queue with an auditable error reason.

### Step 5 — Classification Agent

1. Deterministic rules run first using tenant taxonomy and known mappings.
2. An AI classifier handles unresolved cases using only permitted context.
3. The result is a proposed revenue/expense/category classification with
   evidence, confidence, and version metadata.
4. Sensitive categories, high values, or low confidence require review.

### Step 6 — Reconciliation Agent

1. Candidate generation uses deterministic indexes: tenant, account, currency,
   direction, date window, amount tolerance, and normalized references.
2. Optional semantic scoring may rank candidates, but candidate recall and final
   auto-accept precision are measured separately.
3. The agent emits ranked proposals supporting exact, partial, split, aggregated,
   or fee-adjusted matches.
4. Database constraints and transactional decision services prevent the same
   amount from being consumed incompatibly.

### Step 7 — Review Coordinator

1. The Review Coordinator applies deterministic approval policy using confidence,
   validation status, amount risk, category sensitivity, tenant settings, and
   prior correction patterns.
2. Eligible low-risk proposals can be auto-approved by policy.
3. Ambiguous, high-impact, or policy-sensitive proposals become human review
   tasks.
4. All decisions append audit events and preserve the original agent outputs.

### Step 8 — Business Insight Agent

1. Deterministic query services calculate cashflow aggregates and retrieve
   anomalies or overdue items from approved records, with provisional data
   explicitly marked.
2. The agent turns these facts into concise observations and suggested
   operational actions.
3. A grounding check verifies that each claim cites supplied record IDs and that
   numeric claims agree with calculation outputs.
4. The agent is not allowed to make tax, legal, investment, credit, or solvency
   conclusions.

### Step 9 — Dashboard

1. The frontend requests tenant-scoped read models rather than recomputing
   financial totals in the browser.
2. Dashboard responses include freshness, currency, period, approval state, and
   drill-down identifiers.
3. Users can inspect evidence, approve or correct proposals, and trigger a new
   version of affected aggregates and insights.
4. Corrections append audit events; historical outputs are superseded, not
   overwritten without trace.

## 5. Core Contracts and State

- **Document lifecycle:** `uploaded → scanning → accepted → processing →
  review_required | processed | failed`.
- **Agent step lifecycle:** `scheduled → running → succeeded | retrying |
  review_required | failed | skipped`.
- **Proposal lifecycle:** `generated → validated → pending_review →
  approved | rejected | superseded`.
- **Workflow contract:** includes `workflow_id`, `tenant_id`, `document_id`,
  `workflow_version`, `status`, `current_agent`, `attempt`, timestamps, and
  correlation ID.
- **Agent handoff envelope:** includes `source_agent`, `target_agent`,
  `handoff_type`, schema version, tenant ID, payload reference, confidence,
  validation status, evidence references, and policy flags.
- **Event envelope:** includes event ID, type, schema version, tenant ID,
  aggregate ID/version, occurred time, trace ID, and payload reference.
- **Idempotency:** externally initiated commands accept idempotency keys;
  consumers record processed event IDs; side effects use transactional outbox or
  equivalent atomic publication.

## 6. Scalability Considerations

- Keep API nodes stateless and horizontally scalable; store state in durable
  services.
- Separate interactive API traffic from CPU/GPU/model-heavy workers.
- Partition queue workloads by agent/task class and apply per-tenant quotas to
  prevent noisy neighbors.
- Use direct-to-object-storage uploads and streamed processing for large files.
- Batch OCR or embedding requests only where latency and tenant isolation allow.
- Index candidate matching on tenant, date, amount, account, currency, and
  normalized reference; bound candidate windows before semantic scoring.
- Build dashboard read models asynchronously when transactional queries become
  expensive. Preserve PostgreSQL as source of truth.
- Cache only versioned, tenant-keyed results; never rely on cache invalidation
  alone for financial correctness.
- Apply provider concurrency limits, circuit breakers, exponential backoff, and
  dead-letter handling per agent class.
- Record cost and latency per document, page, workflow step, agent, tenant, and
  model to guide routing and capacity decisions.
- Start as a modular monolith plus workers. Extract services only when scaling,
  ownership, reliability, or regulatory boundaries justify operational cost.

## 7. Security Considerations

- Use OIDC/OAuth 2.1 for identity, short-lived sessions, MFA for privileged
  roles, and role- plus tenant-based authorization on every resource.
- Enforce tenant scope server-side; never trust a tenant identifier supplied by
  the browser without membership validation.
- Encrypt traffic with TLS and data at rest with managed keys. Consider
  per-tenant envelope keys for higher-assurance tiers.
- Store secrets in a secrets manager, rotate them, and prohibit secrets in source
  control, images, logs, prompts, or client bundles.
- Scan uploads, verify type by content, cap file size/page count, and process
  untrusted documents in isolated workers with no unnecessary network access.
- Treat document text as untrusted input and defend against prompt injection:
  delimit content, restrict tools, use allowlisted actions, validate outputs, and
  require policy approval for side effects.
- Enforce tool allowlists per agent. An agent may call only the tools registered
  for its role and tenant policy.
- Minimize provider payloads and use enterprise terms that prohibit training on
  customer data. Make provider and region policy configurable.
- Redact sensitive content from logs and traces. Audit access, download,
  approval, correction, export, deletion, and administrator actions.
- Define retention and deletion workflows covering originals, derivatives,
  backups, caches, vector indexes, evaluation copies, workflow state, agent logs,
  and provider retention.
- Apply least-privilege service identities, private networking, egress controls,
  dependency/image scanning, signed artifacts, and protected deployment
  environments.
- Establish incident response, restore testing, audit review, and jurisdictional
  privacy/accounting assessments before production use.

## 8. Evaluation and Observability

Every AI output captures the dataset-relevant features needed to reproduce it:
agent name, model, provider, prompt/configuration version, input artifact
version, tool versions, latency, token/cost usage, validation result, confidence,
and handoff decision. Production telemetry must not store raw prompts or
documents by default.

Release quality combines:

- deterministic unit and contract tests;
- offline task metrics and confidence calibration;
- agent-level evaluations for extraction, validation, classification,
  reconciliation, review routing, and insight grounding;
- workflow replay and failure-injection tests;
- groundedness and policy evaluations for insights;
- shadow or canary comparisons for model and prompt changes;
- online correction, review, latency, cost, drift, and handoff-failure signals.

See [evaluation.md](evaluation.md) for gates and metric definitions.

## 9. Future Cloud Deployment

The initial cloud shape should use managed services and preserve provider
portability:

| Capability | Cloud deployment consideration |
|---|---|
| Web/API | Container platform with autoscaling, private service networking, health probes, and zero-downtime rollout |
| Workers | Independently scaled worker pools by agent/task type, including optional GPU-capable pools |
| Database | Managed PostgreSQL with high availability, point-in-time recovery, encryption, and connection pooling |
| Objects | Versioned object storage with private endpoints, lifecycle policy, malware quarantine, and tenant-aware prefixes |
| Queue | Managed durable queue with dead-letter support, visibility timeouts, ordering only where required, and per-agent topics |
| Identity | Managed OIDC federation, centralized authorization policy, and workload identities |
| Secrets/keys | Managed secrets and KMS/HSM-backed keys with rotation and access audit |
| Observability | OpenTelemetry-compatible collection with region and retention controls |
| Edge | WAF, DDoS protection, TLS termination, upload limits, and rate limiting |

Deployment must support separate environments and accounts/projects, immutable
artifacts promoted through CI/CD, infrastructure as code, database migration
gates, automated rollback, backup restoration drills, and regional data
residency.

Avoid designing around one cloud's proprietary AI API in domain code. Provider
adapters belong in the AI and Tool Service Layer, while durable records use
internal schemas. Multi-region active-active operation should be deferred until
tenant placement, recovery objectives, write consistency, and cost justify its
complexity.

## 10. Architecture Decisions to Resolve Before Implementation

1. Target jurisdictions, currencies, languages, and compliance obligations.
2. Tenant isolation tier: shared schema with row-level security, schema per
   tenant, or database per tenant.
3. Workflow engine and queue selection based on durability and operational
   requirements.
4. Multi-agent orchestration framework and persistence strategy.
5. Object storage and document-processing residency constraints.
6. Initial OCR/model provider set and contractual data-handling guarantees.
7. Canonical accounting taxonomy and the boundary with external ledgers.
8. Confidence and financial-impact thresholds for each auto-approval action.
9. Tool allowlists, redaction policy, and provider-routing rules per agent.
10. Recovery point and recovery time objectives by service and data class.
