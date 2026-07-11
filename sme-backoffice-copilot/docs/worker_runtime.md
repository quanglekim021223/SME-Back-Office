# Distributed workflow workers

Phase 13 uses an application-level `WorkflowJobQueue` boundary. The HTTP API
publishes `DocumentProcessingCommand` payloads; it does not call Celery APIs
from routers or application services.

## Local modes

| `WORKFLOW_QUEUE_MODE` | Runtime | Use case |
| --- | --- | --- |
| `in_process` | `asyncio` worker started by FastAPI | Fast local development and unit tests. |
| `celery` | Redis broker plus a separate Celery process | Docker/local integration and production-like execution. |

Run the distributed local stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

The Compose stack forces `WORKFLOW_QUEUE_MODE=celery`. The API and worker share
the `uploads_data` volume, so a command's local document path is readable by
the worker. Redis exposes port `6379` by default; PostgreSQL remains on `5433`.

For native development, leave `WORKFLOW_QUEUE_MODE=in_process` in `.env` and
start Uvicorn as before. To run native Celery, set the queue mode and start:

```bash
cd backend
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
behaviour. The worker writes only workflow phase metadata to the Celery result
backend; financial document text remains in the configured document storage.

Provider-specific rate limits and durable job indexing are deliberately left to
Phase 13.3, where they can be observed and operated safely.
