from uuid import uuid4

import pytest

from app.providers import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMMessage,
    LLMMessageRole,
    LLMProviderRunContext,
    LLMResponseFormat,
    MockLLMProvider,
    ProviderDataUseCase,
    ProviderDeploymentMode,
    ProviderExecutionError,
    ProviderModelRoute,
    ProviderPrivacyAction,
    ProviderPrivacyContext,
    ProviderPrivacyGate,
    ProviderPrivacyPolicy,
    ProviderRouteKind,
    ProviderRoutingConfig,
    ProviderRuntime,
    ProviderTaskType,
    redact_and_minimize_text,
)


class RecordingMockLLMProvider(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.last_request: LLMGenerationRequest | None = None

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        self.last_request = request
        return await super().generate(request=request, context=context)


def test_privacy_gate_allows_non_cloud_provider() -> None:
    gate = ProviderPrivacyGate()

    decision = gate.evaluate(
        deployment_mode=ProviderDeploymentMode.LOCAL,
        context=ProviderPrivacyContext(),
    )

    assert decision.allowed is True
    assert decision.action == ProviderPrivacyAction.ALLOW


def test_privacy_gate_blocks_cloud_provider_by_default() -> None:
    gate = ProviderPrivacyGate()

    decision = gate.evaluate(
        deployment_mode=ProviderDeploymentMode.CLOUD,
        context=ProviderPrivacyContext(tenant_allows_cloud=True),
    )

    assert decision.allowed is False
    assert decision.action == ProviderPrivacyAction.BLOCK
    assert "Cloud providers are disabled by policy." in decision.reasons


def test_deidentified_cloud_evaluation_policy_blocks_raw_data() -> None:
    gate = ProviderPrivacyGate(
        ProviderPrivacyPolicy(
            allow_cloud_providers=True,
            allowed_cloud_use_cases={ProviderDataUseCase.EVALUATION},
        )
    )

    decision = gate.evaluate(
        deployment_mode=ProviderDeploymentMode.CLOUD,
        context=ProviderPrivacyContext(
            use_case=ProviderDataUseCase.EVALUATION,
            is_deidentified=False,
            tenant_allows_cloud=True,
        ),
    )

    assert decision.allowed is False
    assert "Cloud evaluation requires de-identified data." in decision.reasons


def test_deidentified_cloud_evaluation_policy_allows_safe_fixture_data() -> None:
    gate = ProviderPrivacyGate(
        ProviderPrivacyPolicy(
            allow_cloud_providers=True,
            allowed_cloud_use_cases={ProviderDataUseCase.EVALUATION},
        )
    )

    decision = gate.evaluate(
        deployment_mode=ProviderDeploymentMode.CLOUD,
        context=ProviderPrivacyContext(
            use_case=ProviderDataUseCase.EVALUATION,
            is_deidentified=True,
            tenant_allows_cloud=True,
        ),
    )

    assert decision.allowed is True
    assert decision.action == ProviderPrivacyAction.ALLOW_REDACTED
    assert decision.requires_redaction is True
    assert decision.requires_minimization is True


def test_redaction_and_minimization_policy_removes_identifiers() -> None:
    text = (
        "Email owner@example.com, Tax ID: US-123456789, "
        "bank account 4111 1111 1111 1111. " + "x" * 500
    )

    result = redact_and_minimize_text(text, max_chars=128)

    assert "[REDACTED_EMAIL]" in result.text
    assert "[REDACTED_TAX_ID]" in result.text
    assert "[REDACTED_ACCOUNT_NUMBER]" in result.text
    assert result.redaction_count == 3
    assert result.was_truncated is True
    assert result.text.endswith("[TRUNCATED]")


@pytest.mark.asyncio
async def test_provider_runtime_blocks_cloud_route_before_provider_call() -> None:
    provider = RecordingMockLLMProvider()
    runtime = ProviderRuntime(
        ProviderRoutingConfig(
            routes=[
                ProviderModelRoute(
                    task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
                    route_kind=ProviderRouteKind.LLM,
                    provider_name="mock_llm",
                    deployment_mode=ProviderDeploymentMode.CLOUD,
                    response_schema_name="invoice-metadata-group.v1",
                )
            ]
        )
    )

    with pytest.raises(ProviderExecutionError, match="Cloud providers are disabled"):
        await runtime.generate_llm(
            provider=provider,
            task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
            request=llm_request_with_sensitive_content(),
            context=LLMProviderRunContext(tenant_id=uuid4()),
            privacy_context=ProviderPrivacyContext(tenant_allows_cloud=True),
        )

    assert provider.last_request is None


@pytest.mark.asyncio
async def test_provider_runtime_redacts_cloud_llm_request_before_call() -> None:
    provider = RecordingMockLLMProvider()
    runtime = ProviderRuntime(
        ProviderRoutingConfig(
            routes=[
                ProviderModelRoute(
                    task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
                    route_kind=ProviderRouteKind.LLM,
                    provider_name="mock_llm",
                    deployment_mode=ProviderDeploymentMode.CLOUD,
                    response_schema_name="invoice-metadata-group.v1",
                )
            ]
        ),
        privacy_gate=ProviderPrivacyGate(
            ProviderPrivacyPolicy(
                allow_cloud_providers=True,
                allow_sensitive_cloud_payloads=True,
                allowed_cloud_use_cases={ProviderDataUseCase.NORMAL_WORKFLOW},
                max_provider_text_chars=4000,
            )
        ),
    )

    invocation = await runtime.generate_llm(
        provider=provider,
        task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
        request=llm_request_with_sensitive_content(),
        context=LLMProviderRunContext(tenant_id=uuid4()),
        privacy_context=ProviderPrivacyContext(
            tenant_allows_cloud=True,
            contains_financial_data=True,
            contains_personal_data=True,
        ),
    )

    assert provider.last_request is not None
    sanitized_content = provider.last_request.messages[0].content
    assert "owner@example.com" not in sanitized_content
    assert "US-123456789" not in sanitized_content
    assert "4111 1111 1111 1111" not in sanitized_content
    assert "[REDACTED_EMAIL]" in sanitized_content
    assert invocation.privacy_decision is not None
    assert invocation.privacy_decision.action == ProviderPrivacyAction.ALLOW_REDACTED
    assert invocation.privacy_decision.redaction_count == 3


def llm_request_with_sensitive_content() -> LLMGenerationRequest:
    return LLMGenerationRequest(
        messages=[
            LLMMessage(
                role=LLMMessageRole.USER,
                content=(
                    "Invoice from owner@example.com, Tax ID: US-123456789, "
                    "bank account 4111 1111 1111 1111."
                ),
            )
        ],
        response_format=LLMResponseFormat.JSON,
        response_schema_name="invoice-metadata-group.v1",
    )
