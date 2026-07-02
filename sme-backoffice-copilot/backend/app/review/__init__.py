"""Human review workflow contracts and immutable versioning helpers."""

from app.review.contracts import (
    REVIEW_TASK_TYPE_DEFINITIONS,
    ReviewAction,
    ReviewTaskTypeDefinition,
    allowed_actions_for_task_type,
    get_review_task_type_definition,
    task_type_for_target,
)
from app.review.versioning import (
    ImmutableProposalVersioningError,
    ReviewVersionedResource,
    SupersedableRecord,
    SupersessionPlan,
    build_classification_supersession_plan,
    build_invoice_extraction_supersession_plan,
    build_reconciliation_supersession_plan,
    mark_record_superseded,
)

__all__ = [
    "REVIEW_TASK_TYPE_DEFINITIONS",
    "ImmutableProposalVersioningError",
    "ReviewAction",
    "ReviewTaskTypeDefinition",
    "ReviewVersionedResource",
    "SupersedableRecord",
    "SupersessionPlan",
    "allowed_actions_for_task_type",
    "build_classification_supersession_plan",
    "build_invoice_extraction_supersession_plan",
    "build_reconciliation_supersession_plan",
    "get_review_task_type_definition",
    "mark_record_superseded",
    "task_type_for_target",
]
