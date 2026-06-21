# SME Back-Office Copilot — Architecture

## 1. Architectural Goals

The architecture prioritizes correctness, provenance, tenant isolation, human
oversight, and replaceable AI components. It separates deterministic financial
records from probabilistic proposals so that model outputs can be reviewed,
replayed, compared, and rolled back.

Key quality attributes are:

- **Traceability:** every derived value links to its source and processing
  version.
- **Idempotency:** uploads, jobs, events, and state transitions tolerate retries.
- **Isolation:** tenant boundaries apply to storage, queries, queues, caches, and
  observability.
- **Evolvability:** providers, prompts, workflows, and storage implementations
  are behind versioned contracts.
- **Human control:** policy gates determine where approval is mandatory.

## 2. High-Level Architecture

```text
┌──────────────────────────── User / External Systems ───────────────────────────┐
│ Browser UI       Mobile browser       Accounting/Bank connectors (future)      │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ HTTPS / OAuth / Webhooks
                                v
┌──────────────────────── Presentation Layer ────────────────────────────────────┐
│ Next.js web application     API client     Upload/review/dashboard experiences │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Versioned REST API
                                v
┌──────────────────────── Application Layer ─────────────────────────────────────┐
│ FastAPI routes  AuthN/AuthZ  Tenant policy  Use cases  Review & query services │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Commands / queries / job requests
                                v
┌──────────────────────── Agent Workflow Layer ──────────────────────────────────┐
│ Durable orchestration  Checkpoints  Retries  Human gates  Workflow state       │
│ Extraction ──> Classification ──> Matching ──> Insight                         │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Typed task interfaces
                                v
┌────────────────────────── AI Service Layer ────────────────────────────────────┐
│ OCR/document AI  LLM gateway  Embeddings  Model router  Safety/grounding       │
│ Prompt registry  Structured output validation  Cost/quality telemetry          │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Repositories / object access / events
                                v
┌──────────────────────────── Data Layer ────────────────────────────────────────┐
│ PostgreSQL: canonical records, workflow state, audit, provenance               │
│ Object storage: immutable originals and derived artifacts                     │
│ Cache/search/analytics read models (introduced only when justified)            │
└───────────────────────────────┬─────────────────────────────────────────────────┘
                                │ Managed runtime capabilities
                                v
┌──────────────────────── Infrastructure Layer ──────────────────────────────────┐
│ Containers  Queue  Secrets/KMS  IAM  Network  Logs/metrics/traces  CI/CD       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Cross-cutting controls—tenant isolation, encryption, audit, schema versioning,
idempotency, observability, and evaluation—apply to every layer.

## 3. Layered Architecture

The dependency direction is downward. Lower layers must not import presentation
or workflow concerns. Upward communication occurs through return contracts and
events, not direct reverse dependencies.

```text
Presentation Layer
        ↓
Application Layer
        ↓
Agent Workflow Layer
        ↓
AI Service Layer
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

### Agent Workflow Layer

Owns long-running and multi-step control flow. Workflows record explicit state,
step inputs and outputs, model/prompt versions, retry count, confidence, and
human-review status. Each step is idempotent and resumable. A workflow delegates
OCR, classification, matching, calculations, and persistence to services rather
than embedding those implementations in graph nodes.

Agent autonomy is bounded by allowed tools, schemas, time/token/cost budgets, and
approval policy. Financial-impacting transitions use deterministic policy, not
an LLM's self-assessed confidence alone.

### AI Service Layer

Owns adapters for OCR, document understanding, language models, embeddings, and
future specialist models. A model gateway enforces structured output schemas,
timeouts, provider policy, content minimization, version capture, token/cost
budgets, retry rules, and telemetry.

Provider responses are proposals, never canonical records. Validation and
grounding occur before outputs cross into workflow state. Routing decisions use
evaluation evidence and task policy, not ad hoc calls from feature code.

### Data Layer

Owns repositories, persistence mappings, canonical record rules, object access,
provenance, audit events, and query models. PostgreSQL is the initial system of
record for transactional metadata. Object storage holds immutable uploads and
derived page images or text. Binary documents should not be stored in relational
rows.

Canonical records, machine proposals, user approvals, and superseded versions
remain distinct. Tenant ID is mandatory on every tenant-owned record and is
enforced through repository scoping and, where supported, database row-level
security.

### Infrastructure Layer

Owns compute, networking, queueing, managed databases, object storage, secrets,
key management, deployment, backups, disaster recovery, monitoring, and CI/CD.
Local Docker Compose mirrors service boundaries but is not a production topology.
Application code depends on capability interfaces, allowing local and cloud
implementations to differ.

## 4. Primary Data Flow

```text
Upload Invoice
      │
      v
Extraction Agent
      │ structured fields + evidence + confidence
      v
Classification Agent
      │ proposed category + rationale + policy result
      v
Matching Agent
      │ ranked transaction candidates + match decision/review task
      v
Insight Agent
      │ grounded observations over approved/provisional records
      v
Dashboard
```

### Step 1 — Upload invoice

1. The frontend requests an upload session.
2. The application layer authenticates the user, authorizes the organization,
   validates file metadata, and creates a document record plus idempotency key.
3. Prefer direct upload to tenant-scoped object storage using a short-lived
   signed URL. The backend records the content hash, size, media type, and object
   version after upload.
4. Malware scanning and file validation complete before the document becomes
   processable.
5. A durable `DocumentIngested` event starts the workflow. The API returns a job
   ID that the UI can poll or subscribe to.

### Step 2 — Extraction Agent

1. The workflow renders or normalizes the source without changing the original.
2. The AI service selects an approved extractor for the file type and tenant
   policy.
3. Structured invoice fields are validated for schema, arithmetic, dates,
   currency, and duplicate identity.
4. Each field stores source coordinates or text span, confidence, model version,
   prompt/configuration version, and validation status.
5. Invalid or low-confidence required fields create a review task. Successful
   output creates a versioned invoice proposal.

### Step 3 — Classification Agent

1. The workflow provides only required normalized fields, tenant taxonomy, and
   permitted historical examples.
2. Deterministic rules run first; an AI classifier handles unresolved cases.
3. The result is a proposed category with evidence, confidence, and version
   metadata.
4. Policy determines auto-acceptance or review based on confidence, amount,
   category sensitivity, and prior correction behavior.

### Step 4 — Matching Agent

1. Candidate generation uses deterministic indexes: tenant, account, currency,
   direction, date window, amount tolerance, and normalized references.
2. A scorer combines exact features with optional semantic similarity. Candidate
   generation and decision thresholds remain independently measurable.
3. The agent emits a ranked proposal supporting exact, partial, split, or
   aggregated matches.
4. Database constraints and a transactional decision service prevent the same
   amount from being consumed incompatibly.
5. High-confidence, low-risk proposals may be approved by policy; all others
   enter review.

### Step 5 — Insight Agent

1. Deterministic query services calculate cashflow aggregates and retrieve
   anomalies or overdue items from approved records, with provisional data
   explicitly marked.
2. The agent turns these facts into concise observations and suggested
   operational actions.
3. A grounding check verifies that each claim cites supplied record IDs and that
   numeric claims agree with calculation outputs.
4. Unsupported claims are removed or routed to evaluation; the agent does not
   query raw tenant data outside its authorized context.

### Step 6 — Dashboard

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
- **Proposal lifecycle:** `generated → validated → pending_review →
  approved | rejected | superseded`.
- **Workflow contract:** includes `workflow_id`, `tenant_id`, `document_id`,
  `version`, `status`, `current_step`, `attempt`, timestamps, and correlation ID.
- **Event envelope:** includes event ID, type, schema version, tenant ID,
  aggregate ID/version, occurred time, trace ID, and payload reference.
- **Idempotency:** externally initiated commands accept idempotency keys;
  consumers record processed event IDs; side effects use transactional outbox or
  equivalent atomic publication.

## 6. Scalability Considerations

- Keep API nodes stateless and horizontally scalable; store state in durable
  services.
- Separate interactive API traffic from CPU/GPU/model-heavy workers.
- Partition queue workloads by task class and apply per-tenant quotas to prevent
  noisy neighbors.
- Use direct-to-object-storage uploads and streamed processing for large files.
- Batch OCR or embedding requests only where latency and tenant isolation allow.
- Index candidate matching on tenant, date, amount, account, currency, and
  normalized reference; bound candidate windows before semantic scoring.
- Build dashboard read models asynchronously when transactional queries become
  expensive. Preserve PostgreSQL as source of truth.
- Cache only versioned, tenant-keyed results; never rely on cache invalidation
  alone for financial correctness.
- Apply provider concurrency limits, circuit breakers, exponential backoff, and
  dead-letter handling.
- Record cost and latency per document, page, workflow step, tenant, and model to
  guide routing and capacity decisions.
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
- Minimize provider payloads and use enterprise terms that prohibit training on
  customer data. Make provider and region policy configurable.
- Redact sensitive content from logs and traces. Audit access, download,
  approval, correction, export, deletion, and administrator actions.
- Define retention and deletion workflows covering originals, derivatives,
  backups, caches, vector indexes, evaluation copies, and provider retention.
- Apply least-privilege service identities, private networking, egress controls,
  dependency/image scanning, signed artifacts, and protected deployment
  environments.
- Establish incident response, restore testing, audit review, and jurisdictional
  privacy/accounting assessments before production use.

## 8. Evaluation and Observability

Every AI output captures the dataset-relevant features needed to reproduce it:
model, provider, prompt/configuration version, input artifact version, latency,
token/cost usage, validation result, and confidence. Production telemetry must
not store raw prompts or documents by default.

Release quality combines:

- deterministic unit and contract tests;
- offline task metrics and confidence calibration;
- workflow replay and failure-injection tests;
- groundedness and policy evaluations for insights;
- shadow or canary comparisons for model changes;
- online correction, review, latency, cost, and drift signals.

See [evaluation.md](evaluation.md) for gates and metric definitions.

## 9. Future Cloud Deployment

The initial cloud shape should use managed services and preserve provider
portability:

| Capability | Cloud deployment consideration |
|---|---|
| Web/API | Container platform with autoscaling, private service networking, health probes, and zero-downtime rollout |
| Workers | Independently scaled worker pools by task type, including optional GPU-capable pools |
| Database | Managed PostgreSQL with high availability, point-in-time recovery, encryption, and connection pooling |
| Objects | Versioned object storage with private endpoints, lifecycle policy, malware quarantine, and tenant-aware prefixes |
| Queue | Managed durable queue with dead-letter support, visibility timeouts, ordering only where required, and per-task topics |
| Identity | Managed OIDC federation, centralized authorization policy, and workload identities |
| Secrets/keys | Managed secrets and KMS/HSM-backed keys with rotation and access audit |
| Observability | OpenTelemetry-compatible collection with region and retention controls |
| Edge | WAF, DDoS protection, TLS termination, upload limits, and rate limiting |

Deployment must support separate environments and accounts/projects, immutable
artifacts promoted through CI/CD, infrastructure as code, database migration
gates, automated rollback, backup restoration drills, and regional data
residency.

Avoid designing around one cloud's proprietary AI API in domain code. Provider
adapters belong in the AI service layer, while durable records use internal
schemas. Multi-region active-active operation should be deferred until tenant
placement, recovery objectives, write consistency, and cost justify its
complexity.

## 10. Architecture Decisions to Resolve Before Implementation

1. Target jurisdictions, currencies, languages, and compliance obligations.
2. Tenant isolation tier: shared schema with row-level security, schema per
   tenant, or database per tenant.
3. Workflow engine and queue selection based on durability and operational
   requirements.
4. Object storage and document-processing residency constraints.
5. Initial OCR/model provider set and contractual data-handling guarantees.
6. Canonical accounting taxonomy and the boundary with external ledgers.
7. Confidence and financial-impact thresholds for each auto-approval action.
8. Recovery point and recovery time objectives by service and data class.

