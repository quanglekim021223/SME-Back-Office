"""Durable workflow job delivery, claiming, heartbeat, and recovery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.contracts import DocumentProcessingCommand, WorkflowJobQueue
from app.models.base import utc_now
from app.models.jobs import (
    OutboxEvent,
    OutboxEventStatus,
    WorkflowJobStatus,
)
from app.models.workflow import WorkflowRunStatus
from app.observability.metrics import metrics_registry
from app.repositories.jobs import WorkflowJobRepository
from app.workflows.contracts import WorkflowState, WorkflowStateStatus
from app.workflows.runtime import WorkflowRuntimeService

logger = logging.getLogger("app.workflow_jobs")

TERMINAL_JOB_STATUSES = {
    WorkflowJobStatus.SUCCEEDED.value,
    WorkflowJobStatus.DEAD_LETTERED.value,
    WorkflowJobStatus.CANCELLED.value,
}
TERMINAL_SUCCESS_WORKFLOW_STATUSES = {
    WorkflowRunStatus.COMPLETED.value,
    WorkflowRunStatus.REVIEW_REQUIRED.value,
}


@dataclass(frozen=True, slots=True)
class JobClaim:
    """Result of an idempotent durable job claim."""

    claimed: bool
    reason: str
    attempt_count: int = 0


class WorkflowJobRuntimeService:
    """Coordinate worker execution against durable job leases."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds

    async def claim(
        self, command: DocumentProcessingCommand, *, worker_id: str
    ) -> JobClaim:
        """Claim a job once, skipping duplicates and active leases."""

        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            job = await repository.get_job(command.job_id, for_update=True)
            if job is None:
                return JobClaim(claimed=False, reason="job_missing")
            if job.idempotency_key != str(command.workflow_run_id):
                return JobClaim(claimed=False, reason="idempotency_mismatch")
            if job.status in TERMINAL_JOB_STATUSES:
                return JobClaim(
                    claimed=False,
                    reason=f"job_{job.status}",
                    attempt_count=job.attempt_count,
                )

            workflow_run = await repository.get_workflow_run_unscoped(
                command.workflow_run_id
            )
            if workflow_run is None:
                return JobClaim(claimed=False, reason="workflow_run_missing")
            if workflow_run.status in TERMINAL_SUCCESS_WORKFLOW_STATUSES:
                job.status = WorkflowJobStatus.SUCCEEDED.value
                job.finished_at = utc_now()
                await session.commit()
                return JobClaim(
                    claimed=False,
                    reason="workflow_already_materialized",
                    attempt_count=job.attempt_count,
                )

            now = utc_now()
            if (
                job.status == WorkflowJobStatus.RUNNING.value
                and job.lease_expires_at is not None
                and job.lease_expires_at > now
            ):
                return JobClaim(
                    claimed=False,
                    reason="active_lease",
                    attempt_count=job.attempt_count,
                )

            job.status = WorkflowJobStatus.RUNNING.value
            job.attempt_count += 1
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            job.worker_id = worker_id
            job.last_error_code = None
            job.last_error_message = None
            await session.commit()
            metrics_registry.record_queue_started(
                queue_latency_ms=_duration_ms(job.enqueued_at, now)
            )
            return JobClaim(
                claimed=True,
                reason="claimed",
                attempt_count=job.attempt_count,
            )

    async def heartbeat(self, job_id: UUID, *, worker_id: str) -> bool:
        """Renew a running job lease from a separate short DB transaction."""

        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            job = await repository.get_job(job_id, for_update=True)
            if (
                job is None
                or job.status != WorkflowJobStatus.RUNNING.value
                or job.worker_id != worker_id
            ):
                return False
            now = utc_now()
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            await session.commit()
            return True

    async def mark_succeeded(self, job_id: UUID) -> None:
        """Finish one successfully materialized workflow job."""

        async with self.session_factory() as session:
            job = await WorkflowJobRepository(session).get_job(job_id, for_update=True)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                return
            job.status = WorkflowJobStatus.SUCCEEDED.value
            job.finished_at = utc_now()
            job.heartbeat_at = None
            job.lease_expires_at = None
            await session.commit()
            metrics_registry.record_queue_succeeded()

    async def mark_retrying(
        self,
        command: DocumentProcessingCommand,
        *,
        error: Exception,
        delay_seconds: float,
        worker_id: str,
    ) -> bool:
        """Atomically release the lease and persist workflow retry state."""

        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            job = await repository.get_job(command.job_id, for_update=True)
            if (
                job is None
                or job.status != WorkflowJobStatus.RUNNING.value
                or job.worker_id != worker_id
            ):
                return False
            workflow_run = await repository.get_workflow_run_unscoped(
                command.workflow_run_id
            )
            if workflow_run is None:
                return False
            job.status = WorkflowJobStatus.RETRYING.value
            job.available_at = utc_now() + timedelta(seconds=delay_seconds)
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.last_error_code = type(error).__name__
            job.last_error_message = str(error)
            state = WorkflowState.model_validate(workflow_run.state or {})
            state.max_retries = max(job.max_attempts - 1, 0)
            WorkflowRuntimeService(repository).request_retry(
                workflow_run=workflow_run,
                state=state,
                agent_name="workflow_queue",
                error_code="ERR_WORKFLOW_JOB_RETRY",
                error_message=str(error),
            )
            await session.commit()
            metrics_registry.record_queue_retry()
            return True

    async def mark_dead_lettered(
        self,
        command: DocumentProcessingCommand,
        *,
        error: Exception,
        worker_id: str,
    ) -> bool:
        """Atomically persist terminal job and workflow failure state."""

        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            job = await repository.get_job(command.job_id, for_update=True)
            if (
                job is None
                or job.status != WorkflowJobStatus.RUNNING.value
                or job.worker_id != worker_id
            ):
                return False
            workflow_run = await repository.get_workflow_run_unscoped(
                command.workflow_run_id
            )
            if workflow_run is None:
                return False
            job.status = WorkflowJobStatus.DEAD_LETTERED.value
            job.finished_at = utc_now()
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.last_error_code = type(error).__name__
            job.last_error_message = str(error)
            state = WorkflowState.model_validate(workflow_run.state or {})
            WorkflowRuntimeService(repository).mark_failed(
                workflow_run=workflow_run,
                state=state,
                error_code="ERR_WORKFLOW_EXECUTION_FAILED",
                error_message=str(error),
                dead_letter=True,
            )
            await session.commit()
            metrics_registry.record_queue_failed(dead_lettered=True)
            return True


async def execute_claimed_workflow_job(
    *,
    command: DocumentProcessingCommand,
    execute: Callable[[DocumentProcessingCommand], Awaitable[None]],
    job_runtime: WorkflowJobRuntimeService,
    worker_id: str,
    heartbeat_seconds: float,
) -> JobClaim:
    """Claim once, renew the lease, execute, and persist success."""

    claim = await job_runtime.claim(command, worker_id=worker_id)
    if not claim.claimed:
        logger.info(
            "workflow.job.skipped",
            extra={
                "event": "workflow.job.skipped",
                "workflow_job_id": str(command.job_id),
                "workflow_run_id": str(command.workflow_run_id),
                "reason": claim.reason,
                "correlation_id": command.correlation_id,
            },
        )
        return claim

    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(
            job_runtime=job_runtime,
            job_id=command.job_id,
            worker_id=worker_id,
            heartbeat_seconds=heartbeat_seconds,
        ),
        name=f"workflow-job-heartbeat:{command.job_id}",
    )
    try:
        await execute(command)
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
    await job_runtime.mark_succeeded(command.job_id)
    return claim


async def _heartbeat_loop(
    *,
    job_runtime: WorkflowJobRuntimeService,
    job_id: UUID,
    worker_id: str,
    heartbeat_seconds: float,
) -> None:
    while True:
        await asyncio.sleep(heartbeat_seconds)
        if not await job_runtime.heartbeat(job_id, worker_id=worker_id):
            return


class OutboxDispatcher:
    """Publish committed outbox events and recover expired worker leases."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        queue: WorkflowJobQueue,
        batch_size: int,
        retry_backoff_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.queue = queue
        self.batch_size = batch_size
        self.retry_backoff_seconds = retry_backoff_seconds

    async def dispatch_once(self) -> int:
        """Publish one locked batch and persist delivery outcomes."""

        published = 0
        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            events = await repository.list_dispatchable_outbox(
                now=utc_now(),
                limit=self.batch_size,
            )
            for event in events:
                job = await repository.get_job(event.workflow_job_id, for_update=True)
                if job is None or job.status in TERMINAL_JOB_STATUSES:
                    event.status = OutboxEventStatus.CANCELLED.value
                    continue
                raw_command = event.payload.get("command")
                if not isinstance(raw_command, dict):
                    event.status = OutboxEventStatus.CANCELLED.value
                    event.last_error = "Outbox command payload is missing."
                    continue
                command = DocumentProcessingCommand.model_validate(raw_command)
                try:
                    job_ref = await self.queue.enqueue(command)
                except Exception as exc:
                    event.attempt_count += 1
                    delay = self.retry_backoff_seconds * (
                        2 ** max(event.attempt_count - 1, 0)
                    )
                    event.available_at = utc_now() + timedelta(seconds=delay)
                    event.last_error = str(exc)
                    metrics_registry.record_queue_publish_failure()
                    logger.exception(
                        "workflow.outbox.publish_failed",
                        extra={
                            "event": "workflow.outbox.publish_failed",
                            "workflow_job_id": str(job.id),
                            "workflow_run_id": str(job.workflow_run_id),
                        },
                    )
                    continue

                now = utc_now()
                event.status = OutboxEventStatus.PUBLISHED.value
                event.published_at = now
                event.last_error = None
                job.status = WorkflowJobStatus.PUBLISHED.value
                job.enqueued_at = now
                job.celery_task_id = str(job_ref.job_id)
                published += 1
                metrics_registry.record_queue_enqueued()
            await session.commit()
        return published

    async def recover_stale_jobs(self) -> int:
        """Mark expired leases lost and schedule safe redelivery or dead-letter."""

        recovered = 0
        async with self.session_factory() as session:
            repository = WorkflowJobRepository(session)
            jobs = await repository.list_stale_running_jobs(
                now=utc_now(),
                limit=self.batch_size,
            )
            for job in jobs:
                workflow_run = await repository.get_workflow_run_unscoped(
                    job.workflow_run_id
                )
                if workflow_run is None:
                    continue
                state = WorkflowState.model_validate(workflow_run.state or {})
                if job.attempt_count >= job.max_attempts:
                    job.status = WorkflowJobStatus.DEAD_LETTERED.value
                    job.finished_at = utc_now()
                    WorkflowRuntimeService(repository).mark_failed(
                        workflow_run=workflow_run,
                        state=state,
                        error_code="ERR_WORKFLOW_JOB_LOST",
                        error_message=(
                            "Worker heartbeat expired after retry exhaustion."
                        ),
                        dead_letter=True,
                    )
                    metrics_registry.record_queue_failed(dead_lettered=True)
                else:
                    job.status = WorkflowJobStatus.LOST.value
                    job.worker_id = None
                    job.heartbeat_at = None
                    job.lease_expires_at = None
                    WorkflowRuntimeService(repository).update_workflow_status(
                        workflow_run=workflow_run,
                        state=state,
                        status=WorkflowStateStatus.LOST,
                        error_code="ERR_WORKFLOW_JOB_LOST",
                        error_message=(
                            "Worker heartbeat expired; job will be redelivered."
                        ),
                    )
                    repository.add_outbox_event(
                        OutboxEvent(
                            id=uuid4(),
                            tenant_id=job.tenant_id,
                            workflow_job_id=job.id,
                            aggregate_type="workflow_run",
                            aggregate_id=job.workflow_run_id,
                            event_type="DocumentProcessingRetryRequested",
                            payload={"command": job.command},
                            status=OutboxEventStatus.PENDING.value,
                            available_at=utc_now(),
                        )
                    )
                    metrics_registry.record_queue_lost()
                recovered += 1
            await session.commit()
        return recovered

    async def run(self, *, stop_event: asyncio.Event, poll_seconds: float) -> None:
        """Continuously dispatch and recover until application shutdown."""

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass
            if stop_event.is_set():
                break
            started_at = perf_counter()
            try:
                await self.recover_stale_jobs()
                await self.dispatch_once()
            except Exception:
                logger.exception("workflow.outbox.loop_failed")
            metrics_registry.record_outbox_cycle(
                duration_ms=round((perf_counter() - started_at) * 1000, 2)
            )


class WorkflowJobMetricsService:
    """Build durable tenant-scoped queue metrics across worker processes."""

    def __init__(self, session: AsyncSession) -> None:
        self.repository = WorkflowJobRepository(session)

    async def build(self, *, tenant_id: UUID) -> dict[str, object]:
        jobs = await self.repository.list_jobs_for_metrics(tenant_id=tenant_id)
        status_counts: dict[str, int] = {}
        latencies: list[float] = []
        for job in jobs:
            status_counts[job.status] = status_counts.get(job.status, 0) + 1
            latency = _duration_ms(job.enqueued_at, job.started_at)
            if latency is not None:
                latencies.append(latency)

        return {
            "total_jobs": len(jobs),
            "status_counts": dict(sorted(status_counts.items())),
            "running_jobs": status_counts.get(WorkflowJobStatus.RUNNING.value, 0),
            "retry_count": sum(max(job.attempt_count - 1, 0) for job in jobs),
            "failure_count": sum(
                status_counts.get(status, 0)
                for status in (
                    WorkflowJobStatus.FAILED.value,
                    WorkflowJobStatus.DEAD_LETTERED.value,
                    WorkflowJobStatus.LOST.value,
                )
            ),
            "queue_latency_ms": {
                "count": len(latencies),
                "avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
        }


def _duration_ms(
    started_at: datetime | None, finished_at: datetime | None
) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return max(
        0.0,
        round((finished_at.timestamp() - started_at.timestamp()) * 1000, 2),
    )
