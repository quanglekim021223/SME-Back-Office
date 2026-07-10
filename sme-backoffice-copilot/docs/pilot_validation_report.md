# Pilot Validation Report

Validation date: 2026-07-10

This report records the Phase 12 validation gate for the controlled pilot. It
summarizes test results, evaluation results, and the security/privacy checklist
review against the current MVP scope.

## Test Suite Results

| Suite                   | Command                         | Result | Notes                                       |
| ----------------------- | ------------------------------- | ------ | ------------------------------------------- |
| Backend full test suite | `make test` from `backend/`     | PASS   | 431 passed, 5 skipped, 1 warning.           |
| Frontend lint/typecheck | `npm run lint` from `frontend/` | PASS   | Prettier check and TypeScript check passed. |

Backend warning observed:

- `StarletteDeprecationWarning` from `fastapi.testclient` importing Starlette's
  deprecated `httpx` integration. This is not blocking for pilot validation, but
  should be monitored during dependency upgrades.

## Evaluation Suite Results

| Suite                          | Command                                                              | Result | Notes                                                                           |
| ------------------------------ | -------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------- |
| Local deterministic evaluation | `python -m app.evaluations.runner --format markdown` from `backend/` | PASS   | Dataset `sme_local_v1`; `workflow_replay_scorer` scored 1.00 with 15/15 checks. |

Initial release gate:

| Gate                                    | Threshold | Actual | Result |
| --------------------------------------- | --------: | -----: | ------ |
| `workflow_replay_must_be_deterministic` |      1.00 |   1.00 | PASS   |

## Security Checklist Review

| Area                             | Status                                | Evidence / follow-up                                                                                                                        |
| -------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Secret management convention     | PASS                                  | `security_privacy.md` requires managed secret store outside local development and stable secret names.                                      |
| `.env` usage                     | PASS for local; pilot requires action | `.env` remains local-only. Staging/pilot must inject secrets through a managed store before real tenant data.                               |
| File upload validation           | PASS                                  | MIME type and size validation are implemented and covered by upload tests.                                                                  |
| File processing sandbox strategy | DOCUMENTED GAP                        | `security_privacy.md` defines production sandbox requirements; current MVP still processes locally and should remain controlled-pilot only. |
| Auth/permission placeholders     | PASS for pilot MVP                    | API tests cover role-based placeholder permissions. Real identity provider integration remains out of pilot scope.                          |
| Tenant isolation                 | PASS                                  | Tenant isolation tests passed in backend suite.                                                                                             |
| Audit logging                    | PASS                                  | Audit logging tests passed; review actions retain audit events.                                                                             |
| Observability redaction          | PASS                                  | Tracing/logging conventions avoid raw financial payloads by default; tracing tests passed.                                                  |
| Provider privacy gate            | PASS                                  | Provider privacy tests passed; cloud provider use is gated by configuration.                                                                |

## Privacy Checklist Review

| Area                          | Status                    | Evidence / follow-up                                                                                                                          |
| ----------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Pilot scope limitation        | PASS                      | `pilot_scope.md` narrows supported files, currencies, locales, and use cases.                                                                 |
| Provider data-handling policy | PASS                      | `security_privacy.md` defines provider training, retention, residency, and opt-in requirements.                                               |
| Retention/deletion draft      | PASS with production gaps | Retention/deletion draft exists; exact retention duration and backup deletion behavior must be finalized per tenant contract.                 |
| Prompt-injection controls     | PASS                      | Prompt-injection test policy is documented and unit coverage exists for classification hybrid behavior.                                       |
| Raw financial data in metrics | PASS                      | Ops metrics use operational labels and counters, not raw document text.                                                                       |
| Evaluation data               | PASS                      | Current local evaluation uses repository fixtures; tenant data must be de-identified before becoming evaluation data.                         |
| Backup privacy                | DOCUMENTED GAP            | `operations_runbook.md` requires encrypted backups and deletion-window policy; tenant deletion across backups remains an open production gap. |

## Validation Decision

The current repository passes the Phase 12 validation gate for a controlled
pilot, with these limitations:

- Pilot must remain within `pilot_scope.md`.
- Cloud OCR/LLM providers require explicit environment opt-in and provider
  data-handling review.
- Production-grade file-processing sandboxing, durable queueing, and backup
  deletion automation remain open gaps before broader production expansion.
