# Pilot Operations Runbook

This runbook defines the minimum operational process for a controlled pilot. It
is not a full production SRE manual; it is the release gate for running the MVP
with real pilot data.

## Environment Strategy

| Environment             | Purpose                                 | Data                                                    | Providers                                                      | Deployment notes                                                                             |
| ----------------------- | --------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Local development       | Feature work and debugging.             | Synthetic or developer-owned test files.                | Mock/local by default; cloud only by explicit `.env` opt-in.   | Docker Compose or direct backend/frontend dev servers.                                       |
| Staging/pilot rehearsal | Validate releases before pilot use.     | De-identified fixtures and approved sample pilot files. | Same provider routing as pilot, using staging secrets.         | Must run migrations, tests, and evaluation gates before promotion.                           |
| Pilot production        | Controlled pilot with real tenant data. | Real pilot tenant data only.                            | Provider use follows `security_privacy.md` and tenant consent. | Managed database, managed secret store, persistent object storage, monitored service health. |

Production-like environments must not rely on committed `.env` files. Use a
managed secret store and inject settings through environment variables or
platform-native secret mounts.

## Deployment Checklist

Before deploying a pilot build:

1. Confirm the target git revision and image/build artifact.
2. Confirm `APP_ENV`, `DATABASE_URL`, provider settings, tracing settings, and
   upload storage location for the target environment.
3. Run backend lint/tests and frontend type checks.
4. Run the local evaluation suite and confirm the release gate passes.
5. Confirm database backup has completed successfully.
6. Apply database migrations.
7. Deploy backend.
8. Deploy frontend with the matching `NEXT_PUBLIC_API_URL`.
9. Verify `/health`, `/api/v1/ops/metrics`, upload, review queue, invoice list,
   and Ops dashboard.
10. Watch structured logs and Ops metrics for provider failures, endpoint
    latency, review queue backlog, and workflow retry exhaustion.

## Backup Strategy

Pilot data lives in two places:

- PostgreSQL database: tenants, users, documents, workflow runs, invoices,
  transactions, proposals, review tasks, audit events, and insights.
- Upload/artifact storage: original uploaded files and derived artifacts under
  `UPLOAD_STORAGE_ROOT` locally or managed object storage in pilot production.

Minimum pilot backup policy:

| Asset                   | Backup method                                             | Frequency                                   | Retention                                                | Notes                                              |
| ----------------------- | --------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| PostgreSQL              | Managed database snapshot or `pg_dump` equivalent.        | Daily, plus before each migration/deploy.   | 14 days for pilot unless tenant contract says otherwise. | Encrypt backups and restrict access to operators.  |
| Upload/artifact storage | Object storage versioning/snapshot or filesystem archive. | Daily, plus before destructive maintenance. | Match database retention window.                         | Backups must preserve tenant/object keys.          |
| Configuration/secrets   | Secret manager version history.                           | On change.                                  | At least 90 days.                                        | Do not export secrets into normal backup archives. |
| Evaluation reports      | Versioned artifact or repository-adjacent data artifact.  | Each release gate.                          | Keep for the pilot duration.                             | Must not contain raw tenant document text.         |

Backups must follow the retention/deletion policy in `security_privacy.md`.
Tenant deletion requires either backup deletion/anonymization support or a
documented restore-window exception approved before pilot onboarding.

## Restore Strategy

Restore drills should be tested before real pilot onboarding and after any major
database/storage change.

Restore process:

1. Identify restore target time and affected tenant(s).
2. Stop writes for affected environment or tenant.
3. Restore database snapshot into an isolated environment first.
4. Restore upload/artifact storage snapshot or object versions matching the same
   target time.
5. Run migrations only if the restored backup is behind the application schema
   expected by the target build.
6. Verify tenant counts, document counts, invoice counts, review queue counts,
   and sample file download/readability.
7. Promote restored environment or perform targeted data repair only after
   verification.
8. Record restore time, data loss window, affected tenants, and verification
   evidence.

Pilot restore objective:

- RPO: 24 hours for the first pilot unless a tenant agreement requires less.
- RTO: one business day for local/pilot recovery.

## Database Migration Process

Migrations are managed by Alembic under `backend/alembic`.

Local commands from `backend/`:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```

Migration rules:

- Every schema change must have a reviewed Alembic migration.
- Migration files must not contain document parsing, model calls, prompt logic,
  or tenant data.
- Prefer backward-compatible migrations: add nullable columns first, backfill in
  an explicit step, then tighten constraints later.
- Do not drop tenant-owned data in the same release that removes code paths.
- Run migrations in staging before pilot production.
- Take a database backup immediately before pilot production migration.
- Record current revision before and after migration.

Pilot deployment migration sequence:

1. Build and test application artifact.
2. Backup database.
3. Put environment in maintenance mode or pause write-heavy workflows when the
   migration is not clearly online-safe.
4. Run `alembic upgrade head`.
5. Verify `/health` and smoke-test key APIs.
6. Resume traffic/workflows.

## Rollback Process

Rollback must distinguish application rollback from data/schema rollback.

### Application Rollback

Use when the new build has runtime issues but schema remains compatible.

1. Stop or drain the new backend/frontend build.
2. Redeploy the last known-good backend and frontend artifacts.
3. Keep the database at the current revision if the older application remains
   compatible.
4. Verify `/health`, upload, review queue, invoice detail, and Ops dashboard.
5. Record incident notes and blocker for the failed build.

### Migration Rollback

Use only when the migration itself is faulty and a restore/downgrade plan has
been rehearsed.

1. Stop writes.
2. Prefer restoring the pre-migration database snapshot when data correctness is
   uncertain.
3. Use `alembic downgrade -1` only for migrations with a tested downgrade path
   and no destructive data transformation.
4. Restore upload/artifact storage if the release changed file paths or derived
   artifact structure.
5. Redeploy the application version that matches the restored schema.
6. Verify tenant data, sample documents, review tasks, and audit events.

### Provider/Configuration Rollback

Use when OCR/LLM/tracing provider routing causes errors or cost spikes.

1. Set provider configuration back to mock/local or the previous provider.
2. Restart affected workers/API process if settings are process-loaded.
3. Confirm provider failure metrics stop increasing.
4. Reprocess only documents whose workflow state is safe to replay.

## Smoke Tests After Deploy Or Rollback

Run these checks before declaring the environment healthy:

- `GET /health` returns healthy.
- `GET /api/v1/ops/metrics` returns local metrics.
- Upload a supported invoice fixture.
- Approve or inspect the generated review task.
- Confirm classification proposal appears on invoice detail.
- Upload a matching bank statement CSV and confirm reconciliation display.
- Confirm logs contain request/correlation/workflow IDs.
- Confirm no unexpected provider failure spike in Ops metrics.

## Operational Ownership

| Area                            | Owner during pilot       | Backup owner             |
| ------------------------------- | ------------------------ | ------------------------ |
| Release decision                | Product/engineering lead | Backend lead             |
| Database migration              | Backend lead             | Deployment operator      |
| Backup/restore                  | Deployment operator      | Backend lead             |
| Provider configuration          | Backend lead             | Product/engineering lead |
| Review policy threshold changes | Product/engineering lead | Finance pilot owner      |
| Incident notes                  | Deployment operator      | Product/engineering lead |

## Open Production Gaps

These should be closed before expanding beyond a controlled pilot:

- Durable background queue and dead-letter processing.
- Automated CI/CD promotion with signed artifacts.
- Automated backup restore drills.
- Tenant-scoped deletion across backups.
- Managed object storage lifecycle policies.
- Blue/green or canary deployment automation.
