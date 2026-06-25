# Multi-Agent Architecture and Governance

## 1. Operating Model

SME Back-Office Copilot uses a **controlled multi-agent workflow**. Agents are
specialized workflow participants with bounded responsibilities, typed inputs,
typed outputs, allowed tools, retry limits, and explicit handoff rules.

Agents do not own final financial truth. They produce proposals, validations,
rankings, explanations, and routing decisions. Canonical records are created or
changed only through deterministic application services, approval policy, and
human review where required.

## 2. Agent Interaction Diagram

```text
┌──────────────────────┐
│ Document Intake Agent│
└──────────┬───────────┘
           │ DocumentAccepted
           v
┌──────────────────────┐
│ Privacy & Policy Gate│
└──────────┬───────────┘
           │ AllowedProcessingScope
           v
┌──────────────────────┐
│  Extraction Agent    │
└──────────┬───────────┘
           │ ProposedStructuredPayload
           v
┌──────────────────────┐      validation errors       ┌──────────────────────┐
│ QA & Validation Agent│ ───────────────────────────► │ Extraction Agent     │
└──────────┬───────────┘      bounded retry request    └──────────────────────┘
           │ ValidatedPayload
           v
┌──────────────────────┐
│ Classification Agent │
└──────────┬───────────┘
           │ CategorizationProposal
           v
┌──────────────────────┐
│ Reconciliation Agent │
└──────────┬───────────┘
           │ MatchProposal
           v
┌──────────────────────┐
│ Review Coordinator   │ ── low confidence / high impact ──► Human Review Task
└──────────┬───────────┘
           │ ApprovedOrProvisionalRecords
           v
┌──────────────────────┐
│ Business Insight     │
│ Agent                │
└──────────┬───────────┘
           │ GroundedInsights
           v
        Dashboard
```

## 3. Agent Registry

| Agent | Responsibility | Primary inputs | Outputs | Allowed tools | Escalation |
|---|---|---|---|---|---|
| Document Intake Agent | Verify upload integrity, type, duplicate identity, scan result, and processing eligibility. | Document metadata, object reference, hash, tenant policy. | `DocumentAccepted`, `DocumentRejected`, or `DocumentNeedsReview`. | MIME checker, hash service, malware scan result reader, metadata validator. | Reject unsupported or unsafe files; route ambiguous metadata to review. |
| Privacy & Policy Gate | Decide processing scope before model/tool calls. | Tenant policy, document class, user role, provider policy. | Redaction/minimization plan, allowed tools, provider restrictions. | Policy engine, sensitive-field classifier, tokenizer/redactor. | Block external processing or require admin review. |
| Extraction Agent | Convert invoice or statement content into structured payloads with evidence. | Document artifact, OCR text/layout, schema, locale policy. | Proposed invoice fields or statement rows with confidence and evidence. | OCR/document AI, LLM structured output gateway, layout parser. | Retry only when QA gives specific repairable errors; otherwise review. |
| QA & Validation Agent | Detect schema, arithmetic, grounding, date, currency, and consistency errors. | Extraction proposal, source evidence, validation rules. | `ValidatedPayload`, `RepairRequest`, or `ValidationFailed`. | Schema validator, financial math checker, evidence checker. | Retry extraction up to policy limit; then review or DLQ. |
| Classification Agent | Propose revenue/expense/category labels. | Validated records, tenant taxonomy, allowed examples. | Category proposal with confidence, rationale, and evidence. | Rule engine, taxonomy lookup, LLM classifier. | Human review for low confidence or sensitive categories. |
| Reconciliation Agent | Rank payment-to-invoice match candidates. | Invoices, transactions, references, date/amount windows. | Match proposal with candidates, allocation, confidence, and reasons. | SQL search, deterministic matcher, optional vector scorer. | Review for high amount, ambiguous candidates, or policy conflict. |
| Review Coordinator | Apply deterministic approval policy and create human review tasks. | All proposals, validations, confidence scores, tenant policy. | Auto-approval, review task, rejection, or escalation decision. | Policy engine, risk thresholds, audit writer. | Human review for any policy-required decision. |
| Business Insight Agent | Generate grounded weekly operational insights from approved/provisional records. | Aggregates, anomalies, overdue items, citations. | Grounded observations and action suggestions. | Financial aggregator, insight prompt, grounding checker. | Remove unsupported claims; route high-severity issues to evaluation/review. |
| Evaluation Agent | Run offline and replay evaluations against versioned datasets. | Dataset manifests, agent outputs, expected labels. | Scores, regressions, release-gate results. | Evaluation runners, scorers, report generator. | Block release when gates fail. |

## 4. Handoff Protocol

Every handoff between agents uses a versioned envelope:

```text
handoff_id
workflow_id
tenant_id
source_agent
target_agent
handoff_type
schema_version
payload_reference
evidence_references
confidence
validation_status
policy_flags
attempt
created_at
trace_id
```

Rules:

- Agents read only the handoff payload and authorized context for the tenant.
- Large artifacts are passed by reference, not copied into messages.
- Handoffs are persisted before the next agent starts.
- Agent outputs are immutable; corrections create a new version.
- Any agent can request review, but only the Review Coordinator can apply
  auto-approval policy.

## 5. Shared Workflow State

Workflow state is centralized and durable. It may be represented as graph state
inside an orchestrator, but the source of truth is persisted in the data layer.

```text
workflow_id
tenant_id
document_id
workflow_version
status
current_agent
retry_count_by_agent
raw_file_metadata_ref
policy_scope_ref
extracted_payload_ref
validation_result_ref
classification_proposal_ref
reconciliation_proposal_ref
review_task_ids
insight_ids
error_log_refs
created_at
updated_at
completed_at
```

This state supports resume after crash, replay for evaluation, audit review, and
rollback of model/prompt/workflow changes.

## 6. Self-Correction and Retry Policy

Self-correction is allowed only when the receiving agent provides explicit,
bounded, machine-checkable feedback.

Example:

```text
QA result:
- subtotal + tax does not equal total
- invoice date is after due date
- supplier name has no source evidence

Action:
- request Extraction Agent repair attempt 2 of 3
```

Retries must be capped by:

- maximum attempts per agent;
- maximum workflow runtime;
- cost budget;
- provider error policy;
- confidence improvement threshold.

After retry exhaustion, the item moves to human review or a dead-letter queue
with a clear reason.

## 7. Human Review Gates

Human review is mandatory when:

- required fields are missing or ungrounded;
- confidence falls below tenant policy;
- amount exceeds the auto-approval threshold;
- candidate matches conflict with existing allocations;
- category is sensitive or frequently corrected;
- provider/tool policy was partially restricted;
- insight claims are material but not sufficiently grounded.

Human corrections are stored as new versions and may become governed evaluation
examples after consent, de-identification, and dataset approval.

## 8. Tool Governance

Tools are granted per agent, not globally.

- Intake agents cannot call LLMs unless explicitly approved.
- Extraction agents cannot approve records.
- Insight agents cannot query arbitrary raw documents.
- Reconciliation agents cannot mutate canonical allocations directly.
- Evaluation agents cannot access raw production data unless the dataset has
  approved governance metadata.

Tool calls capture tool name, version, input artifact reference, output artifact
reference, latency, cost, and policy result.

## 9. Failure Modes

| Failure mode | Handling |
|---|---|
| Unsupported file format | Reject or route to review with reason. |
| Malware or unsafe content | Quarantine and block processing. |
| Prompt injection in document text | Treat source text as untrusted; restrict tools; validate outputs. |
| Extraction hallucination | QA validation, source evidence checks, bounded retry, review. |
| Ambiguous reconciliation | Ranked candidates plus human review. |
| Agent timeout/provider failure | Retry with backoff, fallback provider if approved, or DLQ. |
| Cross-tenant access attempt | Deny, audit, alert. |
| Cost budget exceeded | Stop workflow and route to review/admin action. |

## 10. Implementation Boundary

The first implementation should be a modular monolith plus background workers.
Agents can be implemented as workflow nodes calling internal services. Separate
microservices should be introduced only when scale, isolation, team ownership, or
regulatory boundaries require them.
