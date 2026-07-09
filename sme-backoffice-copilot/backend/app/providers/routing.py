"""Model routing, provider runtime policies, and cost tracking."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import StrEnum
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from app.observability.metrics import metrics_registry
from app.providers.base import ProviderDeploymentMode
from app.providers.errors import ProviderExecutionError
from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProvider,
    LLMProviderRunContext,
)
from app.providers.ocr import (
    OCRInput,
    OCRProvider,
    OCRProviderRunContext,
    OCRResult,
)
from app.providers.privacy import (
    ProviderPrivacyContext,
    ProviderPrivacyDecision,
    ProviderPrivacyGate,
)


class ProviderTaskType(StrEnum):
    """Provider-routable AI tasks used by workflow agents."""

    DOCUMENT_OCR = "document_ocr"
    INVOICE_METADATA_EXTRACTION = "invoice_metadata_extraction"
    INVOICE_TABLE_EXTRACTION = "invoice_table_extraction"
    INVOICE_TOTALS_EXTRACTION = "invoice_totals_extraction"
    INVOICE_CLASSIFICATION = "invoice_classification"
    BUSINESS_INSIGHT_GENERATION = "business_insight_generation"


class ProviderRouteKind(StrEnum):
    """Provider route adapter family."""

    OCR = "ocr"
    LLM = "llm"


class ProviderModelRoute(BaseModel):
    """One task-to-provider routing rule."""

    model_config = ConfigDict(extra="forbid")

    task_type: ProviderTaskType
    route_kind: ProviderRouteKind
    provider_name: str = Field(min_length=1)
    deployment_mode: ProviderDeploymentMode = ProviderDeploymentMode.LOCAL
    model_name: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    response_schema_name: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)
    retry_backoff_seconds: float | None = Field(default=None, ge=0)
    input_cost_per_1k_tokens: Decimal = Decimal("0.00")
    output_cost_per_1k_tokens: Decimal = Decimal("0.00")
    currency: str = Field(default="USD", min_length=3, max_length=3)
    metadata: dict[str, object] = Field(default_factory=dict)


class ProviderRoutingConfig(BaseModel):
    """Provider routing configuration for local and cloud model selection."""

    model_config = ConfigDict(extra="forbid")

    default_timeout_seconds: float = Field(default=30.0, gt=0)
    default_max_retries: int = Field(default=1, ge=0)
    default_retry_backoff_seconds: float = Field(default=0.0, ge=0)
    routes: list[ProviderModelRoute] = Field(default_factory=list)

    def route_for(self, task_type: ProviderTaskType) -> ProviderModelRoute:
        """Return the configured route for one provider task."""

        for route in self.routes:
            if route.task_type == task_type:
                return route
        raise ProviderExecutionError(f"No provider route configured for {task_type}.")

    def runtime_policy_for(self, route: ProviderModelRoute) -> ProviderRuntimePolicy:
        """Resolve route-specific timeout/retry values against defaults."""

        return ProviderRuntimePolicy(
            timeout_seconds=route.timeout_seconds or self.default_timeout_seconds,
            max_retries=route.max_retries
            if route.max_retries is not None
            else self.default_max_retries,
            retry_backoff_seconds=route.retry_backoff_seconds
            if route.retry_backoff_seconds is not None
            else self.default_retry_backoff_seconds,
        )


class ProviderRuntimePolicy(BaseModel):
    """Timeout and retry policy for one provider invocation."""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    retry_backoff_seconds: float = Field(default=0.0, ge=0)

    @property
    def max_attempts(self) -> int:
        """Return total attempts including the first call."""

        return self.max_retries + 1


class ProviderUsageCost(BaseModel):
    """Estimated provider usage cost for one invocation."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    model_name: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    input_cost: Decimal = Decimal("0.00")
    output_cost: Decimal = Decimal("0.00")
    total_cost: Decimal = Decimal("0.00")
    currency: str = Field(default="USD", min_length=3, max_length=3)


class LLMProviderInvocationResult(BaseModel):
    """LLM provider result plus runtime metadata."""

    model_config = ConfigDict(extra="forbid")

    route: ProviderModelRoute
    attempts: int = Field(ge=1)
    result: LLMGenerationResult
    cost: ProviderUsageCost
    privacy_decision: ProviderPrivacyDecision | None = None


class OCRProviderInvocationResult(BaseModel):
    """OCR provider result plus runtime metadata."""

    model_config = ConfigDict(extra="forbid")

    route: ProviderModelRoute
    attempts: int = Field(ge=1)
    result: OCRResult
    privacy_decision: ProviderPrivacyDecision | None = None


class ProviderRuntime:
    """Execute provider calls with timeout, retry, and cost tracking."""

    def __init__(
        self,
        routing_config: ProviderRoutingConfig,
        privacy_gate: ProviderPrivacyGate | None = None,
    ) -> None:
        self.routing_config = routing_config
        self.privacy_gate = privacy_gate or ProviderPrivacyGate()

    async def generate_llm(
        self,
        *,
        provider: LLMProvider,
        task_type: ProviderTaskType,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
        privacy_context: ProviderPrivacyContext | None = None,
    ) -> LLMProviderInvocationResult:
        """Run an LLM provider call using configured route policies."""

        route = self.routing_config.route_for(task_type)
        if route.route_kind != ProviderRouteKind.LLM:
            raise ProviderExecutionError(
                f"Route {task_type.value} is not configured for LLM generation."
            )
        if route.provider_name != provider.name:
            raise ProviderExecutionError(
                f"Route expects provider {route.provider_name}, got {provider.name}."
            )

        policy = self.routing_config.runtime_policy_for(route)
        privacy_decision = self.privacy_gate.require_allowed(
            deployment_mode=route.deployment_mode,
            context=privacy_context,
        )
        enriched_request = enrich_llm_request_from_route(request=request, route=route)
        sanitized_request, privacy_decision = self.privacy_gate.sanitize_llm_request(
            request=enriched_request,
            decision=privacy_decision,
        )
        started_at = perf_counter()
        try:
            result, attempts = await call_with_policy(
                lambda: provider.generate(
                    request=sanitized_request,
                    context=context,
                ),
                policy=policy,
                provider_name=provider.name,
            )
        except Exception:
            metrics_registry.record_provider_call(
                task_type=task_type.value,
                provider_name=provider.name,
                model_name=route.model_name,
                attempts=policy.max_attempts,
                duration_ms=elapsed_ms(started_at),
                success=False,
            )
            raise
        cost = estimate_llm_cost(route=route, result=result)
        metrics_registry.record_provider_call(
            task_type=task_type.value,
            provider_name=provider.name,
            model_name=result.model_name or route.model_name,
            attempts=attempts,
            duration_ms=elapsed_ms(started_at),
            success=True,
            input_tokens=cost.input_tokens,
            output_tokens=cost.output_tokens,
            total_cost=cost.total_cost,
        )
        return LLMProviderInvocationResult(
            route=route,
            attempts=attempts,
            result=result,
            cost=cost,
            privacy_decision=privacy_decision,
        )

    async def extract_ocr(
        self,
        *,
        provider: OCRProvider,
        task_type: ProviderTaskType,
        input_data: OCRInput,
        context: OCRProviderRunContext,
        privacy_context: ProviderPrivacyContext | None = None,
    ) -> OCRProviderInvocationResult:
        """Run an OCR provider call using configured route policies."""

        route = self.routing_config.route_for(task_type)
        if route.route_kind != ProviderRouteKind.OCR:
            raise ProviderExecutionError(
                f"Route {task_type.value} is not configured for OCR extraction."
            )
        if route.provider_name != provider.name:
            raise ProviderExecutionError(
                f"Route expects provider {route.provider_name}, got {provider.name}."
            )

        policy = self.routing_config.runtime_policy_for(route)
        privacy_decision = self.privacy_gate.require_allowed(
            deployment_mode=route.deployment_mode,
            context=privacy_context,
        )
        sanitized_input, privacy_decision = self.privacy_gate.sanitize_ocr_input(
            input_data=input_data,
            decision=privacy_decision,
        )
        started_at = perf_counter()
        try:
            result, attempts = await call_with_policy(
                lambda: provider.extract_text(
                    input_data=sanitized_input,
                    context=context,
                ),
                policy=policy,
                provider_name=provider.name,
            )
        except Exception:
            metrics_registry.record_provider_call(
                task_type=task_type.value,
                provider_name=provider.name,
                model_name=route.model_name,
                attempts=policy.max_attempts,
                duration_ms=elapsed_ms(started_at),
                success=False,
            )
            raise
        metrics_registry.record_provider_call(
            task_type=task_type.value,
            provider_name=provider.name,
            model_name=route.model_name,
            attempts=attempts,
            duration_ms=elapsed_ms(started_at),
            success=True,
        )
        return OCRProviderInvocationResult(
            route=route,
            attempts=attempts,
            result=result,
            privacy_decision=privacy_decision,
        )


async def call_with_policy[ProviderOperationResult](
    operation_factory: Callable[[], Awaitable[ProviderOperationResult]],
    *,
    policy: ProviderRuntimePolicy,
    provider_name: str,
) -> tuple[ProviderOperationResult, int]:
    """Call an async provider operation with timeout and retry policy."""

    last_error: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return (
                await asyncio.wait_for(
                    operation_factory(),
                    timeout=policy.timeout_seconds,
                ),
                attempt,
            )
        except TimeoutError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc

        if attempt < policy.max_attempts and policy.retry_backoff_seconds > 0:
            await asyncio.sleep(policy.retry_backoff_seconds)

    raise ProviderExecutionError(
        f"Provider {provider_name} failed after {policy.max_attempts} attempt(s)."
    ) from last_error


def elapsed_ms(started_at: float) -> float:
    """Return elapsed milliseconds from a monotonic start time."""

    return round((perf_counter() - started_at) * 1000, 2)


def enrich_llm_request_from_route(
    *,
    request: LLMGenerationRequest,
    route: ProviderModelRoute,
) -> LLMGenerationRequest:
    """Apply prompt and schema defaults from route when request omits them."""

    return request.model_copy(
        update={
            "prompt_id": request.prompt_id or route.prompt_id,
            "prompt_version": request.prompt_version or route.prompt_version,
            "response_schema_name": (
                request.response_schema_name or route.response_schema_name
            ),
            "metadata": {
                **request.metadata,
                "provider_route_task_type": route.task_type.value,
                "provider_route_model_name": route.model_name,
            },
        }
    )


def estimate_llm_cost(
    *,
    route: ProviderModelRoute,
    result: LLMGenerationResult,
) -> ProviderUsageCost:
    """Estimate token-based provider cost from route prices."""

    input_tokens = result.input_tokens or 0
    output_tokens = result.output_tokens or 0
    input_cost = token_cost(input_tokens, route.input_cost_per_1k_tokens)
    output_cost = token_cost(output_tokens, route.output_cost_per_1k_tokens)
    return ProviderUsageCost(
        provider_name=result.provider_name,
        model_name=result.model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=input_cost + output_cost,
        currency=route.currency,
    )


def token_cost(tokens: int, cost_per_1k_tokens: Decimal) -> Decimal:
    """Return Decimal token cost using a per-1K-token rate."""

    return Decimal(tokens) / Decimal(1000) * cost_per_1k_tokens


def build_default_provider_routing_config(
    *,
    llm_provider_name: str = "mock_llm",
    llm_model_name: str = "mock-llm",
    ocr_provider_name: str = "mock_ocr",
    llm_deployment_mode: ProviderDeploymentMode = ProviderDeploymentMode.MOCK,
    ocr_deployment_mode: ProviderDeploymentMode = ProviderDeploymentMode.MOCK,
    timeout_seconds: float = 30.0,
    max_retries: int = 1,
    retry_backoff_seconds: float = 0.0,
    llm_input_cost_per_1k_tokens: Decimal = Decimal("0.00"),
    llm_output_cost_per_1k_tokens: Decimal = Decimal("0.00"),
) -> ProviderRoutingConfig:
    """Build default local routes for mock/local provider execution."""

    return ProviderRoutingConfig(
        default_timeout_seconds=timeout_seconds,
        default_max_retries=max_retries,
        default_retry_backoff_seconds=retry_backoff_seconds,
        routes=[
            ProviderModelRoute(
                task_type=ProviderTaskType.DOCUMENT_OCR,
                route_kind=ProviderRouteKind.OCR,
                provider_name=ocr_provider_name,
                deployment_mode=ocr_deployment_mode,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ),
            ProviderModelRoute(
                task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
                route_kind=ProviderRouteKind.LLM,
                provider_name=llm_provider_name,
                deployment_mode=llm_deployment_mode,
                model_name=llm_model_name,
                prompt_id="invoice.metadata_extraction",
                prompt_version="0.1.0",
                response_schema_name="invoice-metadata-group.v1",
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                input_cost_per_1k_tokens=llm_input_cost_per_1k_tokens,
                output_cost_per_1k_tokens=llm_output_cost_per_1k_tokens,
            ),
            ProviderModelRoute(
                task_type=ProviderTaskType.INVOICE_TABLE_EXTRACTION,
                route_kind=ProviderRouteKind.LLM,
                provider_name=llm_provider_name,
                deployment_mode=llm_deployment_mode,
                model_name=llm_model_name,
                prompt_id="invoice.table_extraction",
                prompt_version="0.1.0",
                response_schema_name="invoice-table-group.v1",
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                input_cost_per_1k_tokens=llm_input_cost_per_1k_tokens,
                output_cost_per_1k_tokens=llm_output_cost_per_1k_tokens,
            ),
            ProviderModelRoute(
                task_type=ProviderTaskType.INVOICE_TOTALS_EXTRACTION,
                route_kind=ProviderRouteKind.LLM,
                provider_name=llm_provider_name,
                deployment_mode=llm_deployment_mode,
                model_name=llm_model_name,
                prompt_id="invoice.totals_extraction",
                prompt_version="0.1.0",
                response_schema_name="invoice-totals-group.v1",
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                input_cost_per_1k_tokens=llm_input_cost_per_1k_tokens,
                output_cost_per_1k_tokens=llm_output_cost_per_1k_tokens,
            ),
            ProviderModelRoute(
                task_type=ProviderTaskType.INVOICE_CLASSIFICATION,
                route_kind=ProviderRouteKind.LLM,
                provider_name=llm_provider_name,
                deployment_mode=llm_deployment_mode,
                model_name=llm_model_name,
                prompt_id="invoice.classification",
                prompt_version="0.1.0",
                response_schema_name="classification-draft.v1",
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                input_cost_per_1k_tokens=llm_input_cost_per_1k_tokens,
                output_cost_per_1k_tokens=llm_output_cost_per_1k_tokens,
            ),
        ],
    )
