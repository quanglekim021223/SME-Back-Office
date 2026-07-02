"""Human review workflow contracts and task type definitions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.operations import (
    ReviewTargetType,
    ReviewTaskPriority,
    ReviewTaskType,
)


class ReviewAction(StrEnum):
    """Supported human review actions exposed by future review APIs."""

    APPROVE_PROPOSAL = "approve_proposal"
    REJECT_PROPOSAL = "reject_proposal"
    CORRECT_EXTRACTION = "correct_extraction"
    CORRECT_CLASSIFICATION = "correct_classification"
    CORRECT_RECONCILIATION = "correct_reconciliation"
    ACKNOWLEDGE_POLICY = "acknowledge_policy"
    DISMISS_INSIGHT = "dismiss_insight"


class ReviewTaskTypeDefinition(BaseModel):
    """Product contract for one review task family."""

    model_config = ConfigDict(extra="forbid")

    task_type: ReviewTaskType
    target_type: ReviewTargetType
    default_priority: ReviewTaskPriority = ReviewTaskPriority.NORMAL
    allowed_actions: tuple[ReviewAction, ...] = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)


REVIEW_TASK_TYPE_DEFINITIONS: tuple[ReviewTaskTypeDefinition, ...] = (
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.EXTRACTION,
        target_type=ReviewTargetType.INVOICE,
        default_priority=ReviewTaskPriority.HIGH,
        allowed_actions=(
            ReviewAction.APPROVE_PROPOSAL,
            ReviewAction.REJECT_PROPOSAL,
            ReviewAction.CORRECT_EXTRACTION,
        ),
        title="Review extracted invoice fields",
        description=(
            "Used when invoice OCR or extraction output is uncertain, invalid, "
            "or conflicts with deterministic validation."
        ),
    ),
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.CLASSIFICATION,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        allowed_actions=(
            ReviewAction.APPROVE_PROPOSAL,
            ReviewAction.REJECT_PROPOSAL,
            ReviewAction.CORRECT_CLASSIFICATION,
        ),
        title="Review accounting classification",
        description=(
            "Used when a category or revenue/expense direction proposal needs "
            "human approval or correction."
        ),
    ),
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.RECONCILIATION,
        target_type=ReviewTargetType.RECONCILIATION,
        default_priority=ReviewTaskPriority.HIGH,
        allowed_actions=(
            ReviewAction.APPROVE_PROPOSAL,
            ReviewAction.REJECT_PROPOSAL,
            ReviewAction.CORRECT_RECONCILIATION,
        ),
        title="Review invoice-to-transaction match",
        description=(
            "Used when reconciliation candidates are ambiguous, low confidence, "
            "or require manual allocation."
        ),
    ),
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.POLICY,
        target_type=ReviewTargetType.DOCUMENT,
        default_priority=ReviewTaskPriority.URGENT,
        allowed_actions=(ReviewAction.ACKNOWLEDGE_POLICY,),
        title="Review policy or privacy issue",
        description=(
            "Used when a privacy, access-control, malware, or business policy "
            "gate requires human attention."
        ),
    ),
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.INSIGHT,
        target_type=ReviewTargetType.INSIGHT,
        allowed_actions=(
            ReviewAction.APPROVE_PROPOSAL,
            ReviewAction.REJECT_PROPOSAL,
            ReviewAction.DISMISS_INSIGHT,
        ),
        title="Review generated business insight",
        description=(
            "Used when a generated insight should be checked before it is "
            "published or shown as a recommendation."
        ),
    ),
    ReviewTaskTypeDefinition(
        task_type=ReviewTaskType.OTHER,
        target_type=ReviewTargetType.OTHER,
        allowed_actions=(ReviewAction.REJECT_PROPOSAL,),
        title="Review miscellaneous item",
        description="Fallback review task type for unknown or unsupported cases.",
    ),
)

REVIEW_TASK_TYPE_BY_TYPE = {
    definition.task_type: definition for definition in REVIEW_TASK_TYPE_DEFINITIONS
}


def get_review_task_type_definition(
    task_type: ReviewTaskType,
) -> ReviewTaskTypeDefinition:
    """Return the review task definition for a task type."""

    return REVIEW_TASK_TYPE_BY_TYPE[task_type]


def allowed_actions_for_task_type(
    task_type: ReviewTaskType,
) -> tuple[ReviewAction, ...]:
    """Return allowed human actions for one task type."""

    return get_review_task_type_definition(task_type).allowed_actions


def task_type_for_target(target_type: ReviewTargetType) -> ReviewTaskType:
    """Infer the default review task type for a target record type."""

    for definition in REVIEW_TASK_TYPE_DEFINITIONS:
        if definition.target_type == target_type:
            return definition.task_type
    return ReviewTaskType.OTHER
