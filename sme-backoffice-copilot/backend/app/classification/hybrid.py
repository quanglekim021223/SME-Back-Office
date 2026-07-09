"""Hybrid accounting classification helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.classification.rules import (
    CategoryClassificationInput,
    CategoryClassificationResult,
    RuleBasedCategoryClassifier,
)
from app.models.accounting import CategoryType
from app.providers.llm import (
    LLMGenerationRequest,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
)
from app.providers.routing import ProviderRuntime, ProviderTaskType
from app.workflows.contracts import ConfidenceLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryOption:
    """One controlled category option exposed to the classifier."""

    code: str
    category_type: CategoryType
    direction: str
    description: str


CATEGORY_TAXONOMY: tuple[CategoryOption, ...] = (
    CategoryOption(
        code="sales_revenue",
        category_type=CategoryType.REVENUE,
        direction="income",
        description="Customer invoices for products, services, or repairs sold.",
    ),
    CategoryOption(
        code="professional_services",
        category_type=CategoryType.REVENUE,
        direction="income",
        description="Consulting, advisory, retainers, or billable service revenue.",
    ),
    CategoryOption(
        code="software_subscription",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Software, SaaS, cloud hosting, developer tools.",
    ),
    CategoryOption(
        code="repairs_and_maintenance",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Repair labor, replacement parts, maintenance services.",
    ),
    CategoryOption(
        code="meals_and_entertainment",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Restaurants, coffee, meals, catering, entertainment.",
    ),
    CategoryOption(
        code="office_supplies",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Office materials, stationery, small equipment, supplies.",
    ),
    CategoryOption(
        code="rent_expense",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Office rent, lease, coworking space.",
    ),
    CategoryOption(
        code="utilities_expense",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Electricity, water, internet, utilities.",
    ),
    CategoryOption(
        code="uncategorized_revenue",
        category_type=CategoryType.REVENUE,
        direction="income",
        description="Revenue invoice when the specific revenue category is unclear.",
    ),
    CategoryOption(
        code="uncategorized_expense",
        category_type=CategoryType.EXPENSE,
        direction="expense",
        description="Expense invoice when the specific expense category is unclear.",
    ),
    CategoryOption(
        code="uncategorized_other",
        category_type=CategoryType.OTHER,
        direction="other",
        description="Use only when invoice direction and category are unclear.",
    ),
)

TAXONOMY_BY_CODE = {option.code: option for option in CATEGORY_TAXONOMY}


async def classify_with_llm_fallback(
    classification_input: CategoryClassificationInput,
    *,
    tenant_id: UUID,
    document_id: UUID | None = None,
    workflow_run_id: UUID | None = None,
    correlation_id: str | None = None,
    provider_runtime: ProviderRuntime | None = None,
    llm_provider: LLMProvider | None = None,
    privacy_context: object | None = None,
    rule_classifier: RuleBasedCategoryClassifier | None = None,
) -> CategoryClassificationResult:
    """Classify with deterministic rules, then LLM fallback for uncertain cases."""

    rule_result = (rule_classifier or RuleBasedCategoryClassifier()).classify(
        classification_input
    )
    if rule_result.confidence not in {ConfidenceLevel.UNKNOWN, ConfidenceLevel.LOW}:
        return rule_result
    if provider_runtime is None or llm_provider is None:
        return rule_result

    try:
        invocation = await provider_runtime.generate_llm(
            provider=llm_provider,
            task_type=ProviderTaskType.INVOICE_CLASSIFICATION,
            request=LLMGenerationRequest(
                messages=build_classification_messages(
                    classification_input=classification_input,
                    rule_result=rule_result,
                ),
                response_format=LLMResponseFormat.JSON,
                response_schema_name="classification-draft.v1",
                temperature=0.0,
                max_output_tokens=500,
                metadata={"classifier": "llm_category_fallback"},
            ),
            context=LLMProviderRunContext(
                tenant_id=tenant_id,
                document_id=document_id,
                workflow_run_id=workflow_run_id,
                agent_name="classification_agent",
                correlation_id=correlation_id,
            ),
            privacy_context=privacy_context,  # type: ignore[arg-type]
        )
    except Exception as exc:
        cause = exc.__cause__
        logger.warning(
            "LLM classification fallback failed: %s%s",
            exc,
            f" Cause: {cause}" if cause is not None else "",
        )
        return rule_result

    if invocation.result.structured_output is None:
        return rule_result
    return result_from_llm_payload(
        payload=invocation.result.structured_output,
        rule_result=rule_result,
    )


def build_classification_messages(
    *,
    classification_input: CategoryClassificationInput,
    rule_result: CategoryClassificationResult,
) -> list[LLMMessage]:
    """Build a bounded prompt that forces selection from taxonomy."""

    taxonomy_payload = [
        {
            "code": option.code,
            "category_type": option.category_type.value,
            "direction": option.direction,
            "description": option.description,
        }
        for option in CATEGORY_TAXONOMY
    ]
    invoice_payload = {
        "target_type": classification_input.target_type.value,
        "text": classification_input.text,
        "amount": str(classification_input.amount)
        if classification_input.amount is not None
        else None,
        "currency": classification_input.currency,
        "direction": classification_input.direction.value
        if classification_input.direction is not None
        else None,
        "counterparty_name": classification_input.counterparty_name,
        "reference": classification_input.reference,
        "metadata": classification_input.metadata,
        "rule_fallback": {
            "category_code": rule_result.category_code,
            "confidence": rule_result.confidence.value,
            "rationale": rule_result.rationale,
        },
    }
    return [
        LLMMessage(
            role=LLMMessageRole.SYSTEM,
            content=(
                "You classify invoices for accounting. Choose exactly one "
                "category_code from the provided taxonomy. Use only evidence "
                "visible in the invoice payload. If direction is unclear, use "
                "uncategorized_other with low confidence. Return JSON matching "
                "classification-draft.v1 only."
            ),
        ),
        LLMMessage(
            role=LLMMessageRole.USER,
            content=json.dumps(
                {
                    "taxonomy": taxonomy_payload,
                    "invoice": invoice_payload,
                    "required_json_fields": [
                        "schema_version",
                        "classification_status",
                        "subject_type",
                        "subject_ref",
                        "proposed_category_code",
                        "proposed_direction",
                        "rationale",
                        "evidence_refs",
                        "confidence",
                    ],
                },
                sort_keys=True,
            ),
        ),
    ]


def result_from_llm_payload(
    *,
    payload: dict[str, object],
    rule_result: CategoryClassificationResult,
) -> CategoryClassificationResult:
    """Map validated-ish LLM classification payload into category result."""

    category_code = string_value(payload.get("proposed_category_code"))
    option = TAXONOMY_BY_CODE.get(category_code or "")
    if option is None:
        return rule_result

    confidence = confidence_value(payload.get("confidence"))
    rationale = string_value(payload.get("rationale")) or (
        f"LLM fallback selected {option.code} from controlled taxonomy."
    )
    evidence_refs = list_value(payload.get("evidence_refs"))

    return CategoryClassificationResult(
        category_code=option.code,
        category_type=option.category_type,
        proposed_direction=option.direction,
        confidence=confidence,
        score=rule_result.score,
        matched_rule_ids=rule_result.matched_rule_ids,
        matched_keywords=rule_result.matched_keywords,
        rationale=rationale,
        metadata={
            **rule_result.metadata,
            "classifier_name": "llm_category_fallback",
            "taxonomy_category_code": option.code,
            "llm_evidence_refs": evidence_refs,
            "rule_fallback_category_code": rule_result.category_code,
            "rule_fallback_confidence": rule_result.confidence.value,
        },
    )


def string_value(value: object) -> str | None:
    """Return a stripped string or None."""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def list_value(value: object) -> list[str]:
    """Return a string list from provider output."""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def confidence_value(value: Any) -> ConfidenceLevel:
    """Normalize provider confidence into the internal enum."""

    if isinstance(value, str):
        try:
            return ConfidenceLevel(value.lower())
        except ValueError:
            pass
    return ConfidenceLevel.LOW


def build_invoice_classification_text(
    *,
    invoice_number: str | None,
    supplier_name: str | None,
    customer_name: str | None,
    line_item_descriptions: list[str],
) -> str:
    """Build compact invoice text for post-extraction classification."""

    return " ".join(
        part
        for part in [
            invoice_number,
            supplier_name,
            customer_name,
            *line_item_descriptions,
        ]
        if part
    )
