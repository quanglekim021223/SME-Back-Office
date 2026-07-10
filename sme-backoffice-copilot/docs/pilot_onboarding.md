# Pilot Onboarding Guide

This guide helps a pilot operator or reviewer start using SME Back-Office
Copilot safely within the controlled pilot scope. It assumes the pilot has
already passed the validation gate recorded in
[Pilot Validation Report](pilot_validation_report.md).

## Pilot Roles

| Role               | Responsibilities                                                                                     |
| ------------------ | ---------------------------------------------------------------------------------------------------- |
| Pilot operator     | Upload supported invoices and bank statement CSVs, monitor processing, report issues.                |
| Human reviewer     | Approve, reject, or correct extraction, classification, and reconciliation proposals.                |
| Finance owner      | Confirms categories, review policy, and whether proposed records are acceptable for pilot reporting. |
| Technical operator | Starts services, checks logs/Ops metrics, handles provider configuration and incidents.              |

## Before The First Session

Confirm these items before uploading real pilot files:

- The tenant and users are approved for a controlled pilot.
- The tenant's files fit the support matrix in
  [Pilot Scope and Support Matrix](pilot_scope.md).
- The tenant understands that the product proposes financial records; it does
  not initiate payments, file taxes, or provide regulated financial advice.
- Cloud OCR/LLM providers are enabled only after provider data-handling review
  and explicit pilot consent.
- Secrets for pilot-like environments are injected from a managed secret store,
  not committed `.env` files.
- The latest release passed tests, evaluation, and smoke checks.

## Supported Pilot Files

Use these formats for the first pilot:

| File type       | Supported input                                                                          |
| --------------- | ---------------------------------------------------------------------------------------- |
| Invoice/receipt | PDF, PNG, or JPEG; one invoice per file; readable English text or OCR-friendly image.    |
| Bank statement  | CSV; one transaction per row; date, description/counterparty, amount, and currency data. |

Avoid encrypted PDFs, multi-invoice PDFs, screenshots with severe blur,
handwritten receipts, PDF bank statements, XLSX files, and unsupported
languages/locales during the first pilot.

## First Workflow

1. Open the local or pilot application URL.
2. Confirm the correct organization is selected in the sidebar.
3. Go to **Upload**.
4. Select **Invoice or receipt**.
5. Upload a supported invoice file.
6. Wait for the upload and processing status to finish.
7. Go to **Review** if a review task appears.
8. Open the review task and inspect extracted invoice fields.
9. Approve only if invoice number, supplier/customer, dates, currency, totals,
   tax, and line items are correct.
10. Submit a correction when fields are wrong or incomplete.
11. Go to **Invoices** and inspect the invoice detail page.
12. Confirm the classification proposal appears after extraction approval.
13. Upload a matching bank statement CSV from **Upload**.
14. Return to the invoice detail page and confirm the bank reconciliation card
    shows either a matched transaction or an awaiting-match state.

## Review Guidance

Follow [Automation and Human Review Policy](review_policy.md) when deciding
whether to approve, reject, or correct a proposal.

### Extraction Review

Check:

- Invoice number.
- Supplier and customer names.
- Issue date and due date.
- Currency.
- Subtotal, tax, and total.
- Line item descriptions, quantities, unit prices, and totals.

Approve only when the extracted invoice can safely become the source of truth
for downstream classification and reconciliation.

### Classification Review

Check:

- Category label and category type.
- Income vs expense direction.
- Confidence level.
- Rationale and evidence text.
- Whether the category matches the finance owner's expectations.

Low or unknown confidence should stay reviewable. Medium or high confidence may
be shown as a proposal without creating extra work unless the reviewer spots a
business issue.

### Reconciliation Review

Check:

- Bank transaction amount and currency.
- Posted date relative to invoice date and due date.
- Invoice number or payment reference in the transaction description.
- Counterparty similarity.
- Whether another transaction or invoice is a better match.

Exact high-confidence matches can appear directly on the invoice detail page.
Ambiguous, missing, or low-confidence matches should be reviewed.

## Daily Pilot Routine

At the start of a pilot day:

- Open **Ops** and check provider failures, workflow failures, slow endpoints,
  review queue size, and correction rate.
- Open **Review** and clear urgent extraction failures first.
- Upload the day's supported invoice and bank statement files.
- Inspect invoice detail pages for classification and reconciliation proposals.
- Record any confusing review task or incorrect automation result.

At the end of a pilot day:

- Confirm no unexpected urgent review backlog remains.
- Export or record any issue examples needed for evaluation.
- Confirm logs include request IDs, correlation IDs, and workflow run IDs for
  investigated failures.

## What To Report

When reporting an issue, include as much of this as possible:

```text
Tenant:
Environment:
File name:
Document ID:
Invoice ID:
Review task ID:
Workflow run ID:
Correlation/request ID:
Action taken:
Expected result:
Actual result:
Screenshot or log excerpt:
Contains real customer data: yes/no
```

Do not paste raw invoice text, bank account numbers, tax IDs, or customer PII
into normal chat or ticket systems unless the pilot data-handling process allows
it.

## Success Criteria

A pilot session is considered successful when:

- Supported invoices upload and either extract cleanly or route to review.
- Reviewers can approve, reject, or correct proposals.
- Approved invoices show classification proposals.
- Matching bank statement CSV rows reconcile to invoices or show an
  awaiting-match state.
- Ops dashboard and structured logs provide enough information to debug slow or
  failed workflows.
- Any automation mistake can be traced to a document, proposal, review action,
  and audit event.

## Known Pilot Limits

- The app is not a payment or tax-filing system.
- PDF/image bank statements are not supported in the first pilot.
- Broad locale/language coverage is not yet validated.
- Provider calls may be disabled or mocked in local development.
- Production-grade file sandboxing, durable queues, backup deletion automation,
  and real identity provider integration remain expansion work.
