"""Celery application factory used by API publishers and worker processes."""

from __future__ import annotations

from ssl import CERT_REQUIRED

from celery import Celery  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings
from app.jobs.celery_routing import CELERY_QUEUE_BY_PRIORITY


def create_celery_app(settings: Settings | None = None) -> Celery:
    """Create a Redis-backed Celery app with durable priority queues."""

    resolved_settings = settings or get_settings()
    celery_app = Celery(
        "sme_backoffice",
        broker=resolved_settings.celery_broker_url,
        backend=resolved_settings.celery_result_backend,
    )
    celery_config = {
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "task_track_started": True,
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
        # Reduce idle Redis commands while BRPOP waits for new work.
        "broker_transport_options": {
            "polling_interval": (
                resolved_settings.celery_broker_polling_interval_seconds
            ),
        },
        "task_default_queue": CELERY_QUEUE_BY_PRIORITY[
            next(iter(CELERY_QUEUE_BY_PRIORITY))
        ],
        "task_queues": tuple(Queue(name) for name in CELERY_QUEUE_BY_PRIORITY.values()),
        "imports": ("app.workers.tasks",),
    }
    # Upstash uses TLS-only endpoints, while local Docker Redis is plaintext.
    # Celery rejects SSL options paired with a redis:// URL, so configure TLS
    # only when both broker and result backend explicitly use rediss://.
    if (
        resolved_settings.celery_broker_url.startswith("rediss://")
        and resolved_settings.celery_result_backend.startswith("rediss://")
    ):
        celery_config["broker_use_ssl"] = {"ssl_cert_reqs": CERT_REQUIRED}
        celery_config["redis_backend_use_ssl"] = {"ssl_cert_reqs": CERT_REQUIRED}

    celery_app.conf.update(**celery_config)
    return celery_app


celery_app = create_celery_app()
