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

Physical schema, indexes, partitioning, and retention fields should be formalized
through architecture decisions before the first migration.
