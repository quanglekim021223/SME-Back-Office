# Data Model Foundation

## Principles

- Every tenant-owned row contains a non-null `tenant_id`.
- Source documents are immutable; corrected interpretations create new versions.
- Agent outputs, machine proposals, approved records, and audit events are
  separate entities.
- Money uses fixed-precision decimals plus ISO 4217 currency, never binary float.
- Timestamps are stored in UTC; source timezone and original date text are
  retained where relevant.
- Soft deletion does not satisfy privacy deletion by itself.
- Agent handoffs and workflow state are durable and replayable; in-memory graph
  state is not the system of record.

## Conceptual entities

| Entity | Purpose | Important relationships |
|---|---|---|
| Organization | Tenant and policy boundary | Has users, accounts, documents, categories |
| User / Membership | Identity and tenant role | Membership joins a user to an organization |
| Document | Immutable uploaded source metadata | Has object versions, processing runs, invoice proposals |
| Processing Run | Reproducible execution metadata | References document, workflow, model and config versions |
| Agent Definition | Versioned registry entry for a bounded agent role | Defines allowed tools, input/output schemas, retry policy |
| Agent Step Execution | Durable record of one agent invocation | Belongs to workflow run; references handoff, tools, artifacts |
| Agent Handoff | Versioned envelope passed between agents | Connects source agent output to target agent input |
| Invoice | Approved or provisional normalized invoice | Has line items, field evidence, classifications, matches |
| Invoice Field Evidence | Source location and confidence for a field | Belongs to invoice version and document artifact |
| Bank Account | Tenant-owned financial account | Has statement imports and transactions |
| Statement Import | Source statement and import boundaries | Has normalized transactions |
| Transaction | Canonical bank movement | Has classification proposals and reconciliation allocations |
| Category | Tenant or system taxonomy node | Referenced by classification decisions |
| Reconciliation | Decision grouping invoices and transactions | Has one or more amount allocations |
| Review Task | Human decision required by policy | Targets a versioned proposal |
| Insight | Grounded observation for a period | Has claim-to-record citations |
| Workflow Run | Durable orchestration state | Has step executions and review transitions |
| Audit Event | Append-only actor/action/history record | References affected resources and correlation IDs |

## Constraints to preserve

- Unique document content hash within a tenant and ingestion scope.
- Unique source transaction identity within a statement/account import scope.
- Allocation totals cannot exceed available invoice or transaction amounts
  without an explicit adjustment policy.
- Approved versions are immutable; corrections supersede them.
- Cross-tenant foreign keys and queries are prohibited.
- Every insight claim references the exact record and aggregate versions used.
- Every agent step records agent version, tool versions, input artifact
  references, output artifact references, confidence, policy flags, latency, and
  cost where applicable.
- Every agent handoff is immutable and scoped to one tenant and workflow run.
- Agent outputs cannot directly mutate approved financial records; approval must
  pass through deterministic policy or human review.

Physical schema, indexes, partitioning, and retention fields are formalized
through Alembic migrations and architecture decisions as the system evolves.

## Immutable versioning strategy for proposals and approvals

Financial records must be treated as append-first data. AI-generated outputs and
human decisions should be traceable without losing the original machine proposal.

### Versioned records

The following records are versioned and must not be overwritten in place after
they become approved or externally visible:

- `Invoice`
- `ClassificationProposal`
- `Reconciliation`
- `Insight`

Each versioned record has:

- a stable primary key for that version;
- a `version` field where applicable;
- a `supersedes_*_id` pointer to the previous version where applicable;
- a lifecycle `status`, such as `proposed`, `pending_review`, `approved`,
  `rejected`, or `superseded`;
- evidence, rationale, confidence, source agent, and source agent version fields
  where relevant.

### Approval rule

Approving a proposal must not mutate the proposal payload. The approval decision
is represented by:

1. updating only controlled lifecycle fields needed for queue/query behavior;
2. resolving the related `ReviewTask`, when one exists;
3. appending an `AuditEvent` that records actor, action, resource, correlation
   ID, and before/after state;
4. creating a new superseding version for any correction.

Payload fields such as extracted amounts, category choice, match rationale,
allocations, insight text, evidence references, and confidence are immutable
once approved.

### Correction rule

Corrections create a new record version instead of editing the previous approved
version. The previous version becomes `superseded`, and the new version points to
it through the appropriate `supersedes_*_id` field.

Examples:

- correcting a classification creates a new `ClassificationProposal`;
- correcting a reconciliation creates a new `Reconciliation` with new
  `ReconciliationAllocation` rows;
- regenerating an insight creates a new `Insight`;
- correcting extracted invoice data creates a new `Invoice` version.

### Audit rule

Every approval, rejection, correction, supersession, auto-approval, and manual
override must append an `AuditEvent`. Audit events are append-only and must be
queryable by `tenant_id`, actor, action, resource type, resource ID, and
correlation ID.

### Agent rule

Agents can create proposals, evidence, handoffs, and review tasks. They cannot
directly mutate approved financial truth. Any side effect that changes approval
state must pass through deterministic policy or human review and must append an
audit event.
