# Evaluation Strategy

## Purpose

Evaluation is a release-control system, not a one-time benchmark. It measures
agent quality, workflow quality, confidence calibration, operational cost,
safety, and human burden for every supported document and workflow segment.

## Evaluation layers

1. **Agent/component:** OCR, field extraction, validation, parsing, candidate
   generation, classification, ranking, review routing, and claim grounding.
2. **Workflow:** end-to-end replay from document ingestion through multi-agent
   handoffs, review state, and dashboard impact.
3. **System:** API contracts, idempotency, concurrency, tenant isolation,
   recovery, latency, and cost.
4. **Online:** review rate, correction rate, drift, failures, latency, cost, and
   user-reported quality with tenant-safe telemetry.

## Core metrics

| Capability | Primary metrics |
|---|---|
| Invoice metadata extraction | Field precision/recall/F1, exact match, normalized edit distance, source evidence coverage |
| Invoice table extraction | Row coverage, cell accuracy, line amount accuracy, table structure validity |
| Invoice totals extraction | Exact subtotal/tax/total accuracy, amount-in-words accuracy, arithmetic validity |
| Statement parsing | Row coverage, exact date/amount/direction accuracy, duplicate rate, balance consistency |
| QA and validation | Schema pass rate, arithmetic-check accuracy, grounding-check accuracy, error-signal precision, false reject rate, missed-error rate |
| Targeted self-correction | First-repair success rate, retry count per error type, unnecessary full-retry rate, DLQ rate |
| Classification | Macro/micro F1, top-k accuracy, abstention quality, calibration error |
| Reconciliation | Candidate recall, auto-accept precision, allocation accuracy, false-match financial value |
| Review coordination | Policy agreement rate, correct escalation rate, unsafe auto-approval rate, review queue precision/recall |
| Insights | Claim groundedness, numeric consistency, actionability rubric, unsupported-claim severity |
| Agent orchestration | Handoff success rate, retry effectiveness, dead-letter rate, resumability, workflow replay determinism |
| Operations | p50/p95 latency, failure/retry rate, cost per document/page, review minutes per 100 records |
| Safety/privacy | Cross-tenant access tests, sensitive-data leakage tests, prompt-injection success rate |

## Agent evaluation

Each agent must have an explicit evaluation contract:

- **Inputs:** dataset slice, tenant policy assumptions, tool versions, model
  versions, and prompt/configuration versions.
- **Expected outputs:** labels, accepted schemas, allowed abstentions, and
  required evidence references.
- **Scorers:** deterministic checks for structured fields, financial arithmetic,
  policy agreement, match quality, and grounded insight claims.
- **Failure taxonomy:** extraction miss, hallucinated field, ungrounded claim,
  incorrect category, missed match, unsafe auto-approval, privacy violation,
  timeout, and cost-budget breach.
- **Replayability:** the same workflow version and artifact versions must be
  replayable without depending on mutable prompts or unpinned model routing.

## Dataset governance

Datasets require a versioned manifest describing source, consent or license,
de-identification, locale, format, time range, label policy, reviewer agreement,
known gaps, and permitted uses. Splits should prevent supplier/template or
near-duplicate leakage. Raw production data is not automatically eligible for
evaluation.

Datasets should include both task labels and workflow labels. Task labels cover
fields, rows, categories, matches, and insight claims. Workflow labels cover
expected handoff paths, retry behavior, review routing, and auto-approval
eligibility.

## Release gates

- No regression beyond the approved tolerance on any critical segment.
- Auto-accepted reconciliation precision meets the product threshold with a
  statistically meaningful sample.
- Review Coordinator policy agreement meets the product threshold and unsafe
  auto-approval cases are zero in the critical suite.
- Confidence thresholds are calibrated on held-out data.
- High-severity unsupported insight claims are zero in the release suite.
- Security, privacy, idempotency, and tenant-isolation tests pass.
- Cost and latency remain within declared budgets.
- Model, prompt, tool, handoff schema, agent contract, and workflow versions are
  pinned and rollback-ready.

Exact tolerances become architecture decision records after baseline evaluation.

## Initial local release gates

Before real OCR/LLM providers are enabled, the local foundation must pass a
small deterministic gate:

| Gate | Threshold | Why it matters |
|---|---:|---|
| `workflow_replay_must_be_deterministic` | `workflow_replay_scorer >= 1.00` | The controlled multi-agent skeleton must replay happy path, validation failure, and retry exhaustion paths predictably. |

This first gate intentionally focuses on workflow correctness rather than model
quality. Provider quality gates will be added after real OCR/LLM adapters are
connected and labelled outputs exist for extraction, classification,
reconciliation, review routing, and insight groundedness.

Run locally:

```bash
cd backend
python -m app.evaluations.runner --format markdown
python -m app.evaluations.runner --format json --output ../data/evaluation-report.json
```
