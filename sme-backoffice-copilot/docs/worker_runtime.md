# Distributed workflow workers

Phase 13 uses an application-level `WorkflowJobQueue` boundary. The HTTP API
does not call Celery or Redis. It commits the document, `WorkflowRun`, durable
`WorkflowJob`, and `OutboxEvent` together. A dispatcher publishes the command
only after that transaction commits.

```text
HTTP upload
  -> PostgreSQL transaction (document + workflow run + job + outbox)
  -> 201 Created
  -> outbox dispatcher
  -> WorkflowJobQueue
  -> in-process or Celery worker
  -> idempotent job claim + renewable lease
  -> workflow execution
```

If Redis is unavailable, the upload remains accepted and the pending outbox
event is retried with exponential backoff. A repeated delivery is safe because
the worker claims a unique durable job keyed by `workflow_run_id`.

## Local modes

| `WORKFLOW_QUEUE_MODE` | Runtime | Use case |
| --- | --- | --- |
| `in_process` | `asyncio` worker started by FastAPI | Fast local development and unit tests. |
| `celery` | Redis broker plus a separate Celery process | Docker/local integration and production-like execution. |

Run the distributed local stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

The Compose stack first runs `alembic upgrade head`, then starts the API,
worker, and standalone outbox dispatcher. It forces
`WORKFLOW_QUEUE_MODE=celery`. The API and worker share the `uploads_data`
volume, so a command's local document path is readable by the worker. Redis
exposes port `6379` by default; PostgreSQL remains on `5433`.

For native development, leave `WORKFLOW_QUEUE_MODE=in_process` in `.env` and
start Uvicorn as before. The FastAPI lifespan starts both the in-process queue
consumer and outbox dispatcher. Apply migrations before either mode:

```bash
cd backend
../.venv/bin/python -m alembic upgrade head
```

To run native Celery, set the queue mode and start Redis, then use two shells:

```bash
cd backend
python -m app.workers.outbox_dispatcher

# Separate shell
celery -A app.workers.celery_app:celery_app worker --loglevel=INFO \
  --concurrency=2 \
  --queues=document-processing-high,document-processing-medium,document-processing-low
```

## Priority and scaling

Document jobs route to one of three broker queues:

| Priority | Queue | Typical work |
| --- | --- | --- |
| High | `document-processing-high` | Interactive uploads and reviewer-triggered work. |
| Medium | `document-processing-medium` | Normal background document work. |
| Low | `document-processing-low` | Batch replay and re-evaluation. |

The default worker consumes all three queues. For production, scale by workload
instead of only increasing one worker's concurrency:

```text
OCR-heavy workers      -> high + medium queues, CPU/memory sized for parsing
LLM-heavy workers      -> high + medium queues, provider concurrency limited
Batch/replay workers   -> low queue only, isolated from interactive uploads
```

`CELERY_WORKER_CONCURRENCY` controls processes per worker container.
`CELERY_TASK_MAX_RETRIES` and `CELERY_RETRY_BACKOFF_SECONDS` control task retry
behaviour. Each execution renews a PostgreSQL lease. The dispatcher marks an
expired lease `lost` and safely republishes it, or `dead_lettered` after retry
exhaustion. The worker writes only workflow phase metadata to the Celery result
backend; financial document text remains in the configured document storage.

Provider calls are throttled across worker processes with Redis when
`PROVIDER_RATE_LIMIT_ENABLED=true`. Configure OCR and LLM budgets separately
with `PROVIDER_OCR_REQUESTS_PER_SECOND` and
`PROVIDER_LLM_REQUESTS_PER_SECOND`. Provider retries acquire a fresh token, so
retry storms cannot bypass the shared limit.

The durable queue metrics endpoint is tenant scoped:

```text
GET /api/v1/ops/workflow-jobs
```

It reports status counts, running jobs, retries, failures, and queue latency.
Process-local `/api/v1/ops/metrics` also reports enqueue, start, success,
failure, retry, lost-job, outbox-cycle, and queue-latency signals.

The current Celery task executes the complete document workflow. Multiple
workers and priority queues provide horizontal scaling, but OCR and LLM stages
cannot yet scale independently. That requires decomposing the workflow into
durable stage tasks while preserving the same job and outbox guarantees.
