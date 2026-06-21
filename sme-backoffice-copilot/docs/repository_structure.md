# Repository Structure and Ownership

## Boundary principles

1. Presentation code does not call model providers or databases directly.
2. Routes validate transport concerns and delegate; they do not contain domain
   policy.
3. Services own deterministic use cases. Workflows own multi-step, durable, or
   agentic orchestration.
4. Provider-specific AI code is hidden behind service interfaces so models can
   be evaluated, routed, and replaced.
5. Persistence models are not API contracts. Schemas define data crossing a
   process or layer boundary.
6. Raw financial documents are runtime data, not source code, and must never be
   committed.

## Folder map

| Folder | Responsibility | Ownership boundary | Why it exists |
|---|---|---|---|
| `sme-backoffice-copilot/` | Repository-wide configuration, documentation entry points, and service boundaries. | Staff engineering governs cross-cutting conventions; feature teams own only their bounded areas. | Provides one versioned change and review boundary for the product foundation. |
| `backend/` | Python API, application services, workflows, persistence, and tests. | Backend team owns runtime behavior; frontend and infrastructure consume only published interfaces. | Keeps server-side concerns independently buildable and deployable. |
| `backend/app/` | Backend application package and composition root. | May compose all backend modules; contains no deployment configuration. | Gives the API one importable runtime boundary. |
| `backend/app/models/` | ORM entities, persistence mappings, and database constraints. | Data/backend owners approve changes; models must not leak into public API contracts. | Separates storage representation from transport and workflow state. |
| `backend/app/schemas/` | Pydantic request, response, event, and workflow-state contracts. | Contract changes require consumer review and versioning where externally visible. | Makes boundaries typed, validated, and testable. |
| `backend/app/routes/` | HTTP endpoints, authentication dependencies, request validation, and response mapping. | API owners manage transport behavior; routes delegate business work to services or workflows. | Prevents HTTP concerns from contaminating domain logic. |
| `backend/app/services/` | Deterministic use cases, provider adapters, and reusable domain capabilities. | Backend/domain owners; no HTTP rendering and no long-running orchestration. | Supports testable business capabilities independent of delivery channel. |
| `backend/app/workflows/` | Agent graphs, durable job orchestration, retries, checkpoints, and human-review transitions. | AI platform team owns orchestration; calls services through stable interfaces. | Isolates non-deterministic and long-running control flow. |
| `backend/app/evaluations/` | Evaluation datasets, scorers, runners, and quality gates represented as code. | AI quality owner defines acceptance thresholds; CI may execute them. | Makes model and prompt quality measurable before release. |
| `backend/alembic/` | Ordered relational database migrations. | Backend/data owners author and review; deployment operators execute. | Provides auditable, reversible schema evolution. |
| `backend/tests/` | Unit, integration, contract, API, security, and workflow tests. | Code owners maintain tests alongside behavior; QA owns cross-system acceptance policy. | Protects architecture boundaries and release quality. |
| `frontend/` | Browser application, user interaction, and API client boundary. | Frontend team owns presentation; it never directly accesses persistence or model providers. | Enables independent UI delivery and scaling. |
| `frontend/app/` | Next.js routes, layouts, server/client components, and view-level state. | Frontend owners; shared API types must follow published backend contracts. | Centralizes product-facing navigation and experiences. |
| `infra/` | Local orchestration and future deployment manifests. | Platform/SRE owns; application teams review service requirements. | Keeps environment topology separate from application code. |
| `data/` | Local-only development fixtures and approved evaluation data. | Data governance controls access and retention; application code treats it as external input. | Creates explicit handling zones without mixing data into code. |
| `data/raw_invoices/` | Unmodified invoice samples for local, approved testing. | Restricted to authorized developers; no production customer data in Git. | Preserves source fidelity for ingestion testing. |
| `data/raw_statements/` | Unmodified bank statement samples for local, approved testing. | Same restricted handling as invoices. | Supports parser and ingestion validation across statement formats. |
| `data/labelled/` | De-identified, versioned ground truth and dataset manifests. | Data/AI quality owners approve labels and licensing. | Enables reproducible extraction, matching, and insight evaluations. |
| `docs/` | Product, architecture, data, evaluation, and repository governance decisions. | Staff engineering/product own direction; affected teams review changes. | Keeps implementation aligned around explicit contracts and trade-offs. |

## Expected future subfolders

Create new folders only when a stable boundary emerges. Likely additions include
`services/ai/`, `services/storage/`, `workflows/nodes/`, `tests/contract/`, and
`infra/kubernetes/`. Avoid generic `utils/` modules; place behavior with the
capability that owns it.
