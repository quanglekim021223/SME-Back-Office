from uuid import uuid4

import pytest

from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.observability.metrics import metrics_registry
from app.services.review_tasks import ReviewTaskQueryService


class FakeReviewTaskRepository:
    def __init__(self, *, tasks: list[ReviewTask], total: int, open_total: int) -> None:
        self.tasks = tasks
        self.total = total
        self.open_total = open_total

    async def list_for_tenant(self, **kwargs):
        self.list_kwargs = kwargs
        return self.tasks, self.total

    async def count_for_tenant(self, **kwargs) -> int:
        self.count_kwargs = kwargs
        return self.open_total

    async def get_for_tenant(self, **kwargs):
        del kwargs
        return None


@pytest.mark.asyncio
async def test_list_review_tasks_records_queue_size_metrics() -> None:
    metrics_registry.reset()
    tenant_id = uuid4()
    task = ReviewTask(
        id=uuid4(),
        tenant_id=tenant_id,
        task_type=ReviewTaskType.EXTRACTION.value,
        target_type=ReviewTargetType.INVOICE.value,
        status=ReviewTaskStatus.OPEN.value,
        priority=ReviewTaskPriority.HIGH.value,
        title="Review extracted invoice",
    )
    repository = FakeReviewTaskRepository(tasks=[task], total=3, open_total=2)

    result = await ReviewTaskQueryService(repository).list_review_tasks(
        tenant_id=tenant_id,
        status_filter=ReviewTaskStatus.OPEN,
        task_type=ReviewTaskType.EXTRACTION,
        limit=10,
        offset=0,
    )

    assert result.tasks == [task]
    assert result.total == 3
    assert repository.count_kwargs["status_filter"] == ReviewTaskStatus.OPEN
    snapshot = metrics_registry.snapshot()
    assert snapshot["review_queue_size"][
        f"tenant:{tenant_id}:status:open:type:all"
    ] == 2
    assert snapshot["review_queue_size"][
        f"tenant:{tenant_id}:status:open:type:extraction"
    ] == 3
