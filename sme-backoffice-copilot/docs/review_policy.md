# Automation and Human Review Policy

This policy defines when the pilot system may continue automatically, when it may
create a proposal without human action, and when a human review task is required.
It applies to the controlled pilot scope in
[Pilot Scope and Support Matrix](pilot_scope.md).

## Policy Principles

- Automation may propose financial records, but pilot reporting must distinguish
  proposed, pending-review, approved, rejected, and superseded records.
- Human review is required whenever confidence is low, evidence is incomplete,
  deterministic validation fails, or multiple plausible financial outcomes exist.
- Corrections must supersede prior proposals instead of overwriting history.
- All decisions must preserve audit events, source document links, and evidence
  references.
- The pilot does not initiate payments, submit tax filings, or provide regulated
  financial advice.

## Status Meanings

| Status         | Meaning                                                           | Human action required                                             |
| -------------- | ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| Proposed       | Automation created a candidate record that passed the pilot gate. | No immediate action, but record remains traceable and reversible. |
| Pending review | Automation found uncertainty or risk.                             | Yes. Reviewer must approve, reject, or correct.                   |
| Approved       | Human approved the proposal or extraction result.                 | No, unless later superseded.                                      |
| Rejected       | Human rejected the proposal.                                      | No, unless reprocessed.                                           |
| Superseded     | A correction or newer version replaced this record.               | Inspect replacement record.                                       |

## Auto-Approval Thresholds

For the pilot, "auto-approval" should be interpreted conservatively as
**auto-proposal** unless a human has explicitly approved the record. The system
may proceed to the next workflow step without creating a review task only when
the following gates pass.

| Area               | May continue without review when                                                                                                           | Must create review task when                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Document ingestion | File type, MIME type, size, duplicate check, malware placeholder, and workflow trigger pass.                                               | Unsupported MIME type, duplicate upload, unreadable file, or processing failure.                                                                    |
| Invoice extraction | Required fields are present, totals validate arithmetically, currency is supported, and QA has no blocking error signals.                  | Missing required fields, arithmetic mismatch, invalid currency, OCR/provider failure, ambiguous invoice date, or QA blocking signal.                |
| Classification     | Confidence is `medium` or `high`, rule/LLM rationale is present, and evidence refs link to the invoice.                                    | Confidence is `low` or `unknown`, no category rule matched, rationale is missing, or reviewer changed extraction values materially.                 |
| Reconciliation     | Exactly one candidate exists, deterministic score is at least `85`, amount difference is within tolerance, and currency does not conflict. | No candidate, more than one candidate, score below `85`, currency mismatch, missing amount/date/reference signals, or existing allocation conflict. |
| Business insights  | Insight is based only on approved or clearly marked proposed records and cites source refs.                                                | Insight depends on pending-review records, unsupported currencies/locales, or ungrounded model text.                                                |

## Current Pilot Thresholds

| Signal                                 | Pilot threshold                                                                                                        |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Classification review threshold        | `confidence in {low, unknown}` requires review.                                                                        |
| Reconciliation auto-proposal threshold | `candidate_score >= 85` and exactly one candidate.                                                                     |
| Reconciliation amount tolerance        | Exact amount tolerance is `0.01`; near matches are scored but require review unless total score reaches the gate.      |
| Currency support                       | Currency must be in the configured allow-list; USD is the first pilot reference currency.                              |
| Provider failure                       | Any OCR/LLM provider failure that prevents extraction or classification should route to review or failure diagnostics. |
| Duplicate document                     | Duplicate upload is rejected before workflow processing.                                                               |

## Human Review Policy

Reviewers may perform three actions:

- **Approve:** accept the current proposal as-is. Approval records an audit event
  and may trigger downstream continuation.
- **Reject:** mark the proposal unsuitable. Rejection records an audit event and
  prevents that proposal from affecting reporting.
- **Correct:** submit corrected fields or decision data. Correction creates a
  replacement version and supersedes the prior proposal.

### Extraction Review

Extraction review is required when the invoice proposal is uncertain or failed
validation. After approval or correction:

1. The approved invoice version becomes the source of truth for downstream
   accounting automation.
2. Classification runs on the approved invoice.
3. Reconciliation waits for or matches against bank transactions.

### Classification Review

Classification review is required when the category decision is low confidence
or unknown. A reviewer should verify:

- Category code and category type.
- Revenue vs expense direction.
- Rationale and source evidence.
- Whether the invoice content actually supports the proposed category.

### Reconciliation Review

Reconciliation review is required for ambiguous or low-confidence matches. A
reviewer should verify:

- Transaction amount and currency.
- Posted/value date relative to invoice issue and due dates.
- Invoice number or reference match.
- Counterparty name similarity.
- Whether another invoice or transaction is a better match.

## Materiality and Risk Guidance

The pilot does not yet implement configurable tenant-specific materiality
limits. Until that exists, use these operational rules:

- Any mismatch in currency requires review.
- Any amount mismatch above the deterministic tolerance requires review unless a
  reviewer accepts a correction.
- Any record used for external reporting, tax, payment, or audit deliverables
  must be human-approved first.
- Any tenant-specific category rule should be tested on examples before it is
  allowed to reduce review volume.

## Audit and Evidence Requirements

Every review outcome must retain:

- Tenant ID.
- Actor ID.
- Review task ID.
- Target resource ID.
- Action type.
- Timestamp.
- Reviewer comment when provided.
- Source evidence refs.
- Superseded and replacement resource IDs for corrections.

## Policy Change Process

Threshold changes are product and operations decisions, not prompt-only changes.
Before relaxing a threshold:

1. Add evaluation examples that represent the new case.
2. Run the full test and evaluation suite.
3. Review correction rate and review queue metrics after rollout.
4. Record the policy change in this document and the implementation plan.
