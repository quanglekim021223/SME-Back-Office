# Pilot Scope and Support Matrix

This document defines the supported scope for the first controlled pilot of the
SME Back-Office Copilot MVP. It is intentionally narrower than the long-term
product vision so that extraction, classification, reconciliation, review, and
operations can be validated safely with real users.

## Target Pilot Scope

The initial pilot is for a small number of friendly SME finance operators or
bookkeepers using the system as a supervised back-office workspace.

### In Scope

- Upload invoices or receipts and bank statement CSV files through the local web
  UI.
- Extract structured invoice fields, totals, tax, and line items from supported
  documents.
- Classify approved invoices into accounting categories with confidence and
  rationale.
- Reconcile approved invoices against uploaded bank statement transactions.
- Route uncertain extraction, classification, or reconciliation outputs to human
  review.
- Inspect local operational health through the Ops dashboard and structured
  backend logs.

### Out of Scope

- Payment initiation, bank transfer execution, or money movement.
- Tax filing, legal advice, credit advice, solvency advice, or regulated
  financial advice.
- Fully autonomous bookkeeping without human review gates.
- Multi-tenant production onboarding, billing, or public self-service signup.
- Accounting system write-back to QuickBooks, Xero, ERP, or tax authority
  systems.
- Production-grade background queue infrastructure and horizontal scaling.

## Supported Document Types

| Area                   | Supported in pilot                                                                                                               | Not supported in pilot                                                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Invoice uploads        | PDF, PNG, JPEG invoices and receipts up to 20 MB.                                                                                | HEIC, TIFF, DOCX, XLSX, encrypted PDFs, password-protected files, multi-file invoice packages.                                                 |
| Invoice layout         | Single invoice per file, readable text or OCR-friendly image, common header plus line-item table layouts.                        | Highly handwritten invoices, severe scans, multiple invoices in one file, unsupported languages, documents requiring manual rotation/cropping. |
| Bank statement uploads | CSV bank statements up to 20 MB.                                                                                                 | PDF bank statements, images, XLSX, OFX/QFX/CAMT/MT940, direct bank feeds.                                                                      |
| Bank statement rows    | One transaction per row with date, description/counterparty, amount or debit/credit columns, currency or account-level currency. | Nested tables, merged cells, running-balance-only exports, multi-account files without account identifiers.                                    |

## Supported Currencies

The deterministic currency validator currently accepts this ISO-style
allow-list:

| Currency | Pilot status           | Notes                                                                       |
| -------- | ---------------------- | --------------------------------------------------------------------------- |
| USD      | Primary pilot currency | Required for initial evaluation and demo workflows.                         |
| VND      | Supported by validator | Use for Vietnamese pilot data only after representative examples are added. |
| EUR      | Supported by validator | Needs pilot examples before broad use.                                      |
| GBP      | Supported by validator | Needs pilot examples before broad use.                                      |
| CAD      | Supported by validator | Needs pilot examples before broad use.                                      |
| AUD      | Supported by validator | Needs pilot examples before broad use.                                      |
| SGD      | Supported by validator | Needs pilot examples before broad use.                                      |
| JPY      | Supported by validator | Needs pilot examples before broad use.                                      |

For the first pilot gate, USD is the reference currency. Other allow-listed
currencies may be tested with explicit sample data, but they should not be
marketed as broadly validated until evaluation coverage exists.

## Supported Locales and Languages

| Area                    | Supported in pilot                                 | Notes                                                                                                |
| ----------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| UI language             | English UI copy.                                   | Vietnamese developer/operator notes may exist in docs and conversation, but the app UI is English.   |
| OCR/extraction language | English source documents.                          | Provider settings currently default to English-oriented OCR.                                         |
| Dates                   | ISO dates and common English invoice dates.        | Ambiguous numeric dates such as `02/11/2019` must be validated during review when locale is unclear. |
| Number format           | Decimal point amounts, comma thousands separators. | Comma decimal formats require more locale-specific evaluation before support.                        |
| Timezone                | Tenant/local deployment timezone for display.      | Financial posting dates should come from documents or bank rows, not server clock assumptions.       |

## Pilot Acceptance Gates

Before onboarding a pilot tenant, confirm:

- The tenant's invoice samples match the supported document matrix.
- The tenant can provide bank statement CSV exports in a stable column format.
- The tenant agrees that uncertain results require human review.
- The tenant understands that the system proposes classifications and
  reconciliations; it does not execute payments or submit statutory filings.
- Evaluation examples include at least the tenant's main invoice and bank CSV
  patterns before expanding automation.

## Expansion Candidates

The next scope expansion should be driven by pilot evidence, not assumed demand.
Likely candidates are:

- XLSX bank statement imports.
- PDF bank statements.
- More robust locale handling for VND and Vietnamese documents.
- Multi-invoice PDFs.
- Export/write-back workflows to accounting systems.
