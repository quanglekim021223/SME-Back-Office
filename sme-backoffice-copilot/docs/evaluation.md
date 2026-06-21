# Evaluation Strategy

## Purpose

Evaluation is a release-control system, not a one-time benchmark. It measures
task quality, confidence calibration, operational cost, safety, and human burden
for every supported document and workflow segment.

## Evaluation layers

1. **Component:** OCR, field extraction, parsing, candidate generation,
   classification, ranking, and claim grounding.
2. **Workflow:** end-to-end replay from document ingestion through review state
   and dashboard impact.
3. **System:** API contracts, idempotency, concurrency, tenant isolation,
   recovery, latency, and cost.
4. **Online:** review rate, correction rate, drift, failures, latency, cost, and
   user-reported quality with tenant-safe telemetry.

## Core metrics

| Capability | Primary metrics |
|---|---|
| Invoice extraction | Field precision/recall/F1, exact match, normalized edit distance, arithmetic validity |
| Statement parsing | Row coverage, exact date/amount/direction accuracy, duplicate rate, balance consistency |
| Classification | Macro/micro F1, top-k accuracy, abstention quality, calibration error |
| Reconciliation | Candidate recall, auto-accept precision, allocation accuracy, false-match financial value |
| Insights | Claim groundedness, numeric consistency, actionability rubric, unsupported-claim severity |
| Operations | p50/p95 latency, failure/retry rate, cost per document/page, review minutes per 100 records |
| Safety/privacy | Cross-tenant access tests, sensitive-data leakage tests, prompt-injection success rate |

## Dataset governance

Datasets require a versioned manifest describing source, consent or license,
de-identification, locale, format, time range, label policy, reviewer agreement,
known gaps, and permitted uses. Splits should prevent supplier/template or
near-duplicate leakage. Raw production data is not automatically eligible for
evaluation.

## Release gates

- No regression beyond the approved tolerance on any critical segment.
- Auto-accepted reconciliation precision meets the product threshold with a
  statistically meaningful sample.
- Confidence thresholds are calibrated on held-out data.
- High-severity unsupported insight claims are zero in the release suite.
- Security, privacy, idempotency, and tenant-isolation tests pass.
- Cost and latency remain within declared budgets.
- Model, prompt, schema, and workflow versions are pinned and rollback-ready.

Exact tolerances become architecture decision records after baseline evaluation.

