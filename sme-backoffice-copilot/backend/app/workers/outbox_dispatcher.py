"""Standalone transactional outbox dispatcher process."""

from __future__ import annotations

import asyncio
import signal

from app.core.config import WorkflowQueueMode, get_settings
from app.core.db import async_session_factory
from app.jobs.factory import create_workflow_job_queue
from app.observability.logging_filter import (
    setup_logging_redaction,
    setup_structured_logging,
)
from app.services.workflow_jobs import OutboxDispatcher


async def run_dispatcher() -> None:
    """Run broker delivery and lost-job recovery until SIGINT/SIGTERM."""

    settings = get_settings()
    if settings.workflow_queue_mode is not WorkflowQueueMode.CELERY:
        raise RuntimeError("Standalone outbox dispatcher requires QUEUE_MODE=celery.")

    setup_structured_logging(log_format=settings.log_format.value)
    setup_logging_redaction()
    queue = create_workflow_job_queue(settings)
    dispatcher = OutboxDispatcher(
        session_factory=async_session_factory,
        queue=queue,
        batch_size=settings.outbox_batch_size,
        retry_backoff_seconds=settings.outbox_retry_backoff_seconds,
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)
    await dispatcher.run(
        stop_event=stop_event,
        poll_seconds=settings.outbox_poll_interval_seconds,
    )


def main() -> None:
    """Run the dispatcher CLI."""

    asyncio.run(run_dispatcher())


if __name__ == "__main__":
    main()
