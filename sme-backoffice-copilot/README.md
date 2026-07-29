# SME Back-Office Copilot

A production-oriented, multi-tenant platform for extracting, validating,
reviewing, and reconciling SME financial documents. The system combines
provider-neutral OCR, schema-constrained LLM extraction, deterministic financial
checks, and human approval before proposed data can affect business records.

## What is implemented

- **Hybrid document AI:** Azure Document Intelligence fast path plus local OCR
  adapters (PaddleOCR, ChandraOCR, and Tesseract) with configurable routing and
  fallback.
- **Schema-constrained extraction:** versioned prompts and Pydantic contracts;
  the OpenAI Responses adapter uses native strict Structured Outputs for
  compatible registered schemas and validates every result again inside the
  application.
- **Field-level evidence grounding:** extracted invoice fields retain the exact
  OCR block IDs, page, and bounding polygon used by the human-review UI.
- **Controlled multi-agent workflow:** invoice extraction, classification,
  reconciliation, review coordination, and insight generation with deterministic
  policy gates and LangGraph/custom orchestration modes.
- **Reliable asynchronous processing:** Celery, Redis, transactional outbox,
  idempotent workflow state, replay, tracing, and provider rate limiting.
- **Multi-tenant safety:** tenant-scoped persistence, privacy routing, redacted
  observability, and human-in-the-loop review tasks.
- **Cloud-native delivery:** Docker, Terraform-managed Azure infrastructure, and
  GitHub Actions with OIDC. Merges to `main` run the deployment pipeline to
  Azure.

## Processing flow

```text
Upload → privacy gate → OCR/layout → field-grounded extraction
       → deterministic validation → classification/reconciliation
       → human review when required → approved business records
```

## Start locally

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

- Frontend: `http://localhost:3000`
- API health check: `http://localhost:8000/health`
- API documentation: `http://localhost:8000/docs`

The Docker stack runs document processing through Redis and a separate Celery
worker. Native Uvicorn development remains on the lightweight in-process queue
unless `WORKFLOW_QUEUE_MODE=celery` is configured. See
[worker runtime](docs/worker_runtime.md) for queue modes and worker scaling.

## Development commands

Install local development dependencies:

```bash
make install
```

Run formatting, linting, and tests:

```bash
make format
make lint
make test
```

Run the local deterministic evaluation suite:

```bash
cd backend
python -m app.evaluations.runner --format markdown
python -m app.evaluations.runner --format json --output ../data/evaluation-report.json
```

The evaluation command currently checks the controlled workflow replay scenarios
and applies the initial local release gate before real AI providers are enabled.

Evaluate the running API against a directory of invoice images and paired JSON
annotations (files are paired by basename; `.txt` annotations containing JSON are
supported):

```bash
cd backend
python -m app.evaluations.api_dataset_runner \
  --images /path/to/invoice-images \
  --annotations /path/to/annotations \
  --profile azure \
  --limit 10 \
  --output ../data/api-extraction-baseline.json
```

The runner uploads each invoice, waits for the workflow to finish, loads the
persisted invoice, and reports normalized field accuracy for invoice number,
supplier, supplier/buyer tax IDs, issue date, tax, and total. Start with
`--limit 10`; remove the limit only after the smoke run succeeds. Re-running the
same dataset reuses duplicate documents already stored for the development
tenant.

Provider profiles are selected per evaluation job:

- `azure`: Azure Document Intelligence `prebuilt-invoice`.
- `local`: local PaddleOCR (`pt`) followed by Ollama extraction.
- `hybrid`: Azure `prebuilt-layout` OCR followed by Ollama extraction.

For the local and hybrid profiles, install and start Ollama on the Docker host:

```bash
ollama pull qwen2.5:7b
ollama serve
docker compose -f infra/docker-compose.yml up -d --build backend worker outbox
```

Then run a local baseline:

```bash
cd backend
.venv/bin/python -m app.dev_reset \
  --yes \
  --tenant-id 00000000-0000-4000-8000-000000000001

.venv/bin/python -m app.evaluations.api_dataset_runner \
  --images /path/to/invoice-images \
  --annotations /path/to/annotations \
  --profile local \
  --limit 10 \
  --output ../data/zenodo-local-baseline.json
```

The reset is intentionally required for a fair comparison: document hashes are
deduplicated per tenant, so otherwise a local run could accidentally score the
invoice previously produced by Azure. `--reuse-existing` is available only when
you explicitly want to score stored results rather than rerun the selected
profile.

Before running a downloaded dataset through a cloud OCR provider, verify that
its license and privacy terms permit external processing and that the documents
satisfy the provider privacy policy. Prefer the local OCR profile for datasets
that have not been de-identified.

## LangGraph workflow

The invoice extraction pipeline can run in two orchestration modes controlled
by `WORKFLOW_ORCHESTRATION_MODE` in `.env`:

| Mode             | Value       | Description                                                                             |
| ---------------- | ----------- | --------------------------------------------------------------------------------------- |
| Custom (default) | `custom`    | Sequential Python-native orchestration. No extra dependencies.                          |
| LangGraph        | `langgraph` | Graph-based orchestration using LangGraph `StateGraph`. Requires `langgraph` installed. |

To switch to LangGraph mode:

```bash
# .env
WORKFLOW_ORCHESTRATION_MODE=langgraph
```

Then install the optional dependency:

```bash
cd backend && pip install -e ".[langgraph]"
```

### Graph structure

The LangGraph adapter (`app/workflows/langgraph_adapter.py`) maps the
document-preparation phase into named graph nodes:

```
document_intake → privacy_policy_gate → document_layout_analyzer → [END]
```

Each node wraps the corresponding agent class so that persistence, handoffs,
and QA routing work identically to the custom-orchestration path.

### Checkpoint/replay

LangGraph checkpointing is disabled by default. Enable it in `.env`:

```bash
LANGGRAPH_CHECKPOINTING_ENABLED=true
LANGGRAPH_RECURSION_LIMIT=25   # max nodes visited per run
```

### Local trace/debug for one document

Run the tracing debug command against a single uploaded document:

```bash
cd backend
python -m app.workflows.replay --document-id <uuid> --trace
```

This executes the full workflow replay with `InMemoryTraceProvider` and prints
every recorded trace event to stdout without sending data to any external
backend.

## Tracing

The tracing layer emits structured events at each significant step of the
workflow (OCR call, LLM call, deterministic validators, QA routing, review-task
creation) without ever exposing raw financial or customer data.

### Supported backends

Configure the backend via `TRACING_BACKEND` in `.env`:

| Value                | Backend                                                |
| -------------------- | ------------------------------------------------------ |
| `disabled` (default) | No events emitted. Zero overhead.                      |
| `langfuse`           | Exports to a Langfuse instance (self-hosted or cloud). |
| `langsmith`          | Exports to LangSmith cloud.                            |

#### Langfuse (local self-host)

```bash
# .env
TRACING_BACKEND=langfuse
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
TRACING_PROJECT_NAME=sme-backoffice-copilot-local
```

#### LangSmith (cloud)

```bash
# .env
TRACING_BACKEND=langsmith
LANGSMITH_API_KEY=ls__...
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=sme-backoffice-copilot-local
```

### Redaction guarantee

All trace payloads pass through `RedactingTraceProvider` before export
(enabled by default via `TRACING_REDACTION_ENABLED=true`).

**Fields that are always redacted to `[REDACTED]`:**

- Exact key matches: `supplier_name`, `customer_name`, `supplier_address`,
  `customer_address`, `supplier_tax_id`, `customer_tax_id`, `ocr_text`,
  `ocr_text_preview`, `full_text`, `raw_text`, `raw`, `prompt`, `messages`,
  `input`, `output`, `content`, `metadata`, `payload`, `structured_output`,
  `assembled_invoice`, `line_item`, `party`, `email`, `phone`, `address`,
  `tax_id`.
- Any key containing: `account`, `address`, `email`, `iban`, `phone`,
  `raw_`, `routing`, `tax_id`.

Payloads larger than `TRACING_MAX_PAYLOAD_CHARS` (default 4 000) are replaced
with a `{"_truncated": true, "payload_chars": N, "payload_preview": "..."}` sentinel.

Safe operational metadata (agent name, provider name, model name, token counts,
attempt counts, signal codes, workflow run ID, task type, status) is always
forwarded as-is.

### Traced events

| Event name                          | Emitted by                                                                | Key safe fields                                                          |
| ----------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `ocr.call.started`                  | `DocumentLayoutAnalyzerAgent`                                             | `provider_name`, `document_id`                                           |
| `ocr.call.finished`                 | `DocumentLayoutAnalyzerAgent`                                             | `provider_name`, `text_block_count`, `duration_ms`                       |
| `ocr.call.failed`                   | `DocumentLayoutAnalyzerAgent`                                             | `error_code`, `provider_name`                                            |
| `llm.call.started`                  | `MetadataExtractorAgent` / `TableExtractorAgent` / `TotalsExtractorAgent` | `agent_name`, `schema_name`, `ocr_text_chars`                            |
| `llm.call.finished`                 | same                                                                      | `agent_name`, `model_name`, `attempts`, `input_tokens`, `output_tokens`  |
| `llm.call.failed`                   | same                                                                      | `agent_name`, `error_code`, `error_type`                                 |
| `deterministic_validators.finished` | `QAValidationAgent`                                                       | `signal_codes`, `total_signal_count`                                     |
| `qa.error_signals.built`            | `QAValidationAgent`                                                       | `signal_codes`, `correction_signal_count`, `blocking_signal_count`       |
| `qa.correction_routing`             | `QAValidationAgent`                                                       | `target_agents`, `signal_codes`, `handoff_count`                         |
| `qa.review_required`                | `QAValidationAgent`                                                       | `signal_codes`, `signal_count`                                           |
| `qa.validation_passed`              | `QAValidationAgent`                                                       | `status`                                                                 |
| `review_task.created`               | `WorkflowOutputPersistenceService`                                        | `task_type`, `reason_code`, `priority`, `source_agent`, `has_invoice_id` |

## Documentation

- [Repository structure](docs/repository_structure.md)
- [Product brief](docs/product_brief.md)
- [Architecture](docs/architecture.md)
- [Agent architecture](docs/agent_architecture.md)
- [Security and privacy conventions](docs/security_privacy.md)
- [Operations alerting draft](docs/operations_alerting.md)
- [Pilot operations runbook](docs/operations_runbook.md)
- [Pilot onboarding guide](docs/pilot_onboarding.md)
- [Pilot scope and support matrix](docs/pilot_scope.md)
- [Pilot validation report](docs/pilot_validation_report.md)
- [Automation and human review policy](docs/review_policy.md)
- [Implementation plan](docs/implementation_plan.md)
- [Data model](docs/data_model.md)
- [Evaluation strategy](docs/evaluation.md)
