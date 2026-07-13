# Public Pilot Deployment Topology

This document records the initial managed-service split for the public pilot.
It keeps HTTP serving, durable workflow execution, relational data, and source
documents independently replaceable.

## Managed Service Split

| Responsibility | Selected service | Notes |
| --- | --- | --- |
| Frontend | Vercel | Hosts the Next.js application. Only public API URLs belong in its environment variables. |
| API | Azure Container Apps | Runs FastAPI with HTTPS ingress. |
| Workflow worker | Azure Container Apps | Runs Celery privately, with no public ingress. |
| Outbox dispatcher | Azure Container Apps | Delivers committed workflow jobs privately and independently of the API. |
| Relational database | Neon PostgreSQL | API, worker, and dispatcher use Neon pooled URLs. Migrations use a direct URL only. |
| Queue and distributed rate limiting | Upstash Redis | All hosted Redis URLs must use `rediss://` TLS. |
| Document objects | Azure Blob Storage | Private `documents` container stores originals and derived artifacts. PostgreSQL stores object references only. |
| OCR | Azure AI Document Intelligence | Accessed by the worker using deployment-managed secrets. |

## Environment Boundaries

| Environment | Azure resource group | Data | Credentials |
| --- | --- | --- | --- |
| Local | None | Synthetic or developer-owned test data | Local `.env` only; never reuse hosted credentials. |
| Staging | `rg-sme-backoffice-staging` | De-identified fixtures and approved rehearsal files | Dedicated staging secrets and cloud resources. |
| Production | `rg-sme-backoffice-production` | Controlled pilot tenant data | Dedicated production secrets and cloud resources. |

The current pilot Blob resource is an Azure validation environment. Before
production onboarding, create separate Blob accounts or containers and secrets
for staging and production. Runtime identities will be attached to Azure
Container Apps in Phase 14.2; deployment automation will use a service
principal only where the Azure tenant permits it.

## Configuration Rules

- `.env.example` is a variable inventory only. It must never contain real
  credentials, connection strings, tenant data, or production URLs.
- Hosted secrets live in Azure Key Vault or the Container Apps secret store.
- Backend processes receive `DATABASE_URL`, provider keys, Redis URLs, and Blob
  configuration from the managed secret store.
- Vercel receives only public `NEXT_PUBLIC_*` values, principally the public
  API URL.
- Hosted API, worker, and dispatcher use `WORKFLOW_QUEUE_MODE=celery`; local
  development may use `in_process`.

## Environment Templates

- [`.env.staging.example`](../.env.staging.example) records the non-local
  staging configuration shape.
- [`.env.production.example`](../.env.production.example) records the
  production configuration shape.
- These are deployment inventories, not files to mount into a container. Copy
  each value into Azure Container Apps secrets or non-secret environment
  variables for its matching environment.
