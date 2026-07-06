# Agent orchestration and tracing

## LangGraph adoption scope

LangGraph will be introduced as an orchestration adapter behind the existing
workflow contracts. It should not replace the current persistence, review,
provider, or audit conventions in one step.

Initial scope:

- keep the current custom workflow runtime as the default path;
- add a LangGraph adapter path behind `WORKFLOW_ORCHESTRATION_MODE=langgraph`;
- reuse existing `WorkflowState`, agent contracts, handoff envelopes, and QA
  error signals;
- preserve current `AgentStepExecution` and `AgentHandoff` persistence;
- add graph checkpoint/replay only after the adapter can run the current invoice
  flow end to end.

Out of scope for the first adapter pass:

- replacing API endpoints;
- replacing review-task persistence;
- sending financial payloads to cloud tracing by default;
- changing provider routing semantics.

## Adapter status

The first adapter pass is intentionally narrow:

- `LangGraphWorkflowAdapter` wraps the existing document preparation agents;
- document intake, privacy/policy gate, and document layout analysis are graph
  nodes;
- agent step execution persistence still goes through `WorkflowRuntimeService`;
- graph node transitions still persist normal `AgentHandoff` records;
- when LangGraph is not installed in the local virtualenv, the adapter can run
  the same nodes sequentially for tests and development.

The adapter now also has an invoice extraction entrypoint that runs:

```text
document_intake
→ privacy_policy_gate
→ document_layout_analyzer
→ metadata_extractor
→ table_extractor
→ totals_extractor
→ invoice_assembly
→ qa_validator
```

The QA node has explicit graph outcome edges for `valid`, `retry`,
`review_required`, and `failed`. For now, those outcomes terminate the graph;
the retry self-correction loop, retry exhaustion handling, and graph
checkpointing remain in later Phase 9.6 tasks.

## Tracing backend decision

The first tracing backend target is Langfuse local/self-host.

Rationale:

- financial documents are sensitive, so local/self-host tracing is safer for the
  MVP;
- Langfuse can capture OCR, LLM, validator, retry, routing, and review-task
  spans without requiring cloud traces;
- LangSmith remains a supported configuration option for later cloud-based
  evaluation or team debugging.

Tracing remains disabled by default. Enable it explicitly with:

```env
TRACING_BACKEND=langfuse
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

All trace payloads must pass through redaction/minimization before they leave
the backend process.
