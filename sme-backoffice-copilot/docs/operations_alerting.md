# Operations Alerting Draft

This draft defines production alert candidates for Phase 11. Local development
uses the in-process `/api/v1/ops/metrics` snapshot; production should export the
same signals to a durable metrics backend such as OpenTelemetry, Prometheus, or
managed cloud monitoring.

## Alert Candidates

| Signal                    | Candidate condition                                                                                                | Why it matters                                                       | First response                                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Provider failure spike    | Provider failure rate exceeds 10% over 10 minutes, or one provider has 5 consecutive failures.                     | OCR/LLM output may stop or silently degrade.                         | Check provider status, API credentials, routing config, and fallback provider health.                              |
| Review queue backlog      | Open review queue exceeds the tenant baseline for 30 minutes, or oldest open task age exceeds the agreed SLA.      | Human-in-the-loop work can block reporting and reconciliation.       | Add reviewer capacity, inspect recent extraction/classification errors, and pause noncritical ingestion if needed. |
| High correction rate      | Correction rate exceeds 25% over the last 50 review decisions or a daily window.                                   | Automation quality may be too low even if tasks are completing.      | Review corrected payloads, provider prompts, classification rules, and recent document templates.                  |
| OCR fail rate             | OCR/document processing failures exceed 5% over 30 minutes, or failure tasks with `ERR_OCR_PROVIDER_FAILED` spike. | Invoices cannot reach extraction, classification, or reconciliation. | Check file readability, MIME validation, sandbox health, OCR provider status, and retry behavior.                  |
| Slow endpoint             | p95 latency exceeds 2 seconds for standard API endpoints or 5 seconds for upload/approve workflows.                | The UI feels stuck and reviewers may retry actions.                  | Inspect database latency, provider calls inside request paths, and workflow step timings.                          |
| Workflow retry exhaustion | Retry-exhausted workflow failures exceed 3 in 15 minutes.                                                          | The workflow is unable to recover from an agent/provider failure.    | Trace the workflow correlation ID, inspect failed agent step logs, and replay the document locally.                |

## Production Notes

- Keep `request_id`, `correlation_id`, and `workflow_run_id` on every log and
  metric event so alerts can link to a trace.
- Store per-tenant queue metrics, but avoid putting document contents, OCR text,
  or invoice PII in metric labels.
- Treat local thresholds as starting points. Tune per tenant after real traffic
  establishes a baseline.
- Alert notifications should include the failing provider, endpoint, workflow
  agent, tenant ID, and a link to logs or traces.
