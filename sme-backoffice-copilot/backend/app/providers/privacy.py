"""Privacy gate, de-identification policy, and redaction for AI providers."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.providers.base import ProviderDeploymentMode
from app.providers.errors import ProviderPrivacyPolicyError
from app.providers.llm import LLMGenerationRequest, LLMMessage
from app.providers.ocr import OCRInput


class ProviderDataUseCase(StrEnum):
    """Why data is being sent to a provider."""

    NORMAL_WORKFLOW = "normal_workflow"
    EVALUATION = "evaluation"
    DEVELOPMENT_TEST = "development_test"


class ProviderDataSensitivity(StrEnum):
    """Sensitivity level for provider-bound payloads."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ProviderPrivacyAction(StrEnum):
    """Privacy-gate action for one provider call."""

    ALLOW = "allow"
    ALLOW_REDACTED = "allow_redacted"
    BLOCK = "block"


class ProviderPrivacyContext(BaseModel):
    """Privacy context supplied before sending data to a provider."""

    model_config = ConfigDict(extra="forbid")

    use_case: ProviderDataUseCase = ProviderDataUseCase.NORMAL_WORKFLOW
    sensitivity: ProviderDataSensitivity = ProviderDataSensitivity.CONFIDENTIAL
    is_deidentified: bool = False
    contains_financial_data: bool = True
    contains_personal_data: bool = True
    tenant_allows_cloud: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def is_sensitive(self) -> bool:
        """Return whether the payload should be treated as sensitive."""

        return (
            self.sensitivity
            in {
                ProviderDataSensitivity.CONFIDENTIAL,
                ProviderDataSensitivity.RESTRICTED,
            }
            or self.contains_financial_data
            or self.contains_personal_data
        )


class ProviderRedactionResult(BaseModel):
    """Text redaction and minimization result."""

    model_config = ConfigDict(extra="forbid")

    text: str
    redaction_count: int = Field(ge=0)
    was_truncated: bool = False


class ProviderPrivacyDecision(BaseModel):
    """Decision emitted by the provider privacy gate."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    action: ProviderPrivacyAction
    deployment_mode: ProviderDeploymentMode
    reasons: list[str] = Field(default_factory=list)
    requires_redaction: bool = False
    requires_minimization: bool = False
    redaction_count: int = Field(default=0, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


class ProviderPrivacyPolicy(BaseModel):
    """Configurable policy for provider-bound data handling."""

    model_config = ConfigDict(extra="forbid")

    allow_cloud_providers: bool = False
    allow_sensitive_cloud_payloads: bool = False
    require_tenant_cloud_consent: bool = True
    require_deidentified_for_cloud_evaluation: bool = True
    require_redaction_for_cloud: bool = True
    require_minimization_for_cloud: bool = True
    max_provider_text_chars: int = Field(default=4000, ge=128)
    allowed_cloud_use_cases: set[ProviderDataUseCase] = Field(
        default_factory=lambda: {ProviderDataUseCase.EVALUATION}
    )


class ProviderPrivacyGate:
    """Evaluate and sanitize payloads before provider execution."""

    def __init__(
        self,
        policy: ProviderPrivacyPolicy | None = None,
    ) -> None:
        self.policy = policy or ProviderPrivacyPolicy()

    def evaluate(
        self,
        *,
        deployment_mode: ProviderDeploymentMode,
        context: ProviderPrivacyContext | None = None,
    ) -> ProviderPrivacyDecision:
        """Return whether a provider call is allowed under privacy policy."""

        privacy_context = context or ProviderPrivacyContext()
        if deployment_mode != ProviderDeploymentMode.CLOUD:
            return ProviderPrivacyDecision(
                allowed=True,
                action=ProviderPrivacyAction.ALLOW,
                deployment_mode=deployment_mode,
                reasons=["Provider is not a cloud provider."],
            )

        reasons: list[str] = []
        if not self.policy.allow_cloud_providers:
            reasons.append("Cloud providers are disabled by policy.")
        if (
            self.policy.require_tenant_cloud_consent
            and not privacy_context.tenant_allows_cloud
        ):
            reasons.append("Tenant has not allowed cloud provider processing.")
        if privacy_context.use_case not in self.policy.allowed_cloud_use_cases:
            reasons.append(
                f"Cloud provider use case is not allowed: "
                f"{privacy_context.use_case.value}."
            )
        if (
            privacy_context.use_case == ProviderDataUseCase.EVALUATION
            and self.policy.require_deidentified_for_cloud_evaluation
            and not privacy_context.is_deidentified
        ):
            reasons.append("Cloud evaluation requires de-identified data.")
        if (
            privacy_context.is_sensitive
            and not privacy_context.is_deidentified
            and not self.policy.allow_sensitive_cloud_payloads
        ):
            reasons.append("Sensitive cloud payloads are not allowed.")

        if reasons:
            return ProviderPrivacyDecision(
                allowed=False,
                action=ProviderPrivacyAction.BLOCK,
                deployment_mode=deployment_mode,
                reasons=reasons,
            )

        requires_redaction = self.policy.require_redaction_for_cloud
        requires_minimization = self.policy.require_minimization_for_cloud
        return ProviderPrivacyDecision(
            allowed=True,
            action=ProviderPrivacyAction.ALLOW_REDACTED
            if requires_redaction or requires_minimization
            else ProviderPrivacyAction.ALLOW,
            deployment_mode=deployment_mode,
            reasons=["Cloud provider call allowed by privacy policy."],
            requires_redaction=requires_redaction,
            requires_minimization=requires_minimization,
        )

    def require_allowed(
        self,
        *,
        deployment_mode: ProviderDeploymentMode,
        context: ProviderPrivacyContext | None = None,
    ) -> ProviderPrivacyDecision:
        """Return a decision or raise when the call is blocked."""

        decision = self.evaluate(
            deployment_mode=deployment_mode,
            context=context,
        )
        if not decision.allowed:
            raise ProviderPrivacyPolicyError("; ".join(decision.reasons))
        return decision

    def sanitize_llm_request(
        self,
        *,
        request: LLMGenerationRequest,
        decision: ProviderPrivacyDecision,
    ) -> tuple[LLMGenerationRequest, ProviderPrivacyDecision]:
        """Redact/minimize LLM messages when the decision requires it."""

        if not decision.requires_redaction and not decision.requires_minimization:
            return request, decision

        redaction_count = 0
        sanitized_messages: list[LLMMessage] = []
        for message in request.messages:
            result = redact_and_minimize_text(
                message.content,
                max_chars=self.policy.max_provider_text_chars,
            )
            redaction_count += result.redaction_count
            sanitized_messages.append(
                message.model_copy(update={"content": result.text})
            )

        sanitized_request = request.model_copy(
            update={
                "messages": sanitized_messages,
                "metadata": {
                    **request.metadata,
                    "privacy_action": decision.action.value,
                    "redaction_count": redaction_count,
                },
            }
        )
        sanitized_decision = decision.model_copy(
            update={"redaction_count": redaction_count}
        )
        return sanitized_request, sanitized_decision

    def sanitize_ocr_input(
        self,
        *,
        input_data: OCRInput,
        decision: ProviderPrivacyDecision,
    ) -> tuple[OCRInput, ProviderPrivacyDecision]:
        """Remove local filesystem details and redact OCR metadata for cloud calls."""

        if not decision.requires_redaction and not decision.requires_minimization:
            return input_data, decision

        redaction_count = 0
        sanitized_metadata: dict[str, object] = {}
        for key, value in input_data.metadata.items():
            if isinstance(value, str):
                result = redact_and_minimize_text(
                    value,
                    max_chars=self.policy.max_provider_text_chars,
                )
                redaction_count += result.redaction_count
                sanitized_metadata[key] = result.text
            else:
                sanitized_metadata[key] = value

        sanitized_input = input_data.model_copy(
            update={
                "local_path": None,
                "metadata": {
                    **sanitized_metadata,
                    "privacy_action": decision.action.value,
                    "redaction_count": redaction_count,
                    "local_path_removed": input_data.local_path is not None,
                },
            }
        )
        sanitized_decision = decision.model_copy(
            update={"redaction_count": redaction_count}
        )
        return sanitized_input, sanitized_decision


def build_provider_privacy_policy(
    *,
    allow_cloud_providers: bool = False,
    allow_sensitive_cloud_payloads: bool = False,
    require_deidentified_for_cloud_evaluation: bool = True,
    max_provider_text_chars: int = 4000,
) -> ProviderPrivacyPolicy:
    """Build provider privacy policy from application configuration values."""

    return ProviderPrivacyPolicy(
        allow_cloud_providers=allow_cloud_providers,
        allow_sensitive_cloud_payloads=allow_sensitive_cloud_payloads,
        require_deidentified_for_cloud_evaluation=(
            require_deidentified_for_cloud_evaluation
        ),
        max_provider_text_chars=max_provider_text_chars,
    )


REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[REDACTED_SSN]",
    ),
    (
        re.compile(r"\b(?:\d[ -]?){12,19}\b"),
        "[REDACTED_ACCOUNT_NUMBER]",
    ),
    (
        re.compile(
            r"\b(?:tax id|tin|ein|vat|mst|mã số thuế)\s*[:#-]?\s*[A-Z0-9-]{5,}\b",
            re.IGNORECASE,
        ),
        "[REDACTED_TAX_ID]",
    ),
    (
        re.compile(
            r"\b(?:account|acct|bank account)\s*[:#-]?\s*[A-Z0-9-]{4,}\b",
            re.IGNORECASE,
        ),
        "[REDACTED_ACCOUNT]",
    ),
)


def redact_and_minimize_text(
    text: str,
    *,
    max_chars: int,
) -> ProviderRedactionResult:
    """Redact sensitive identifiers and truncate oversized provider text."""

    redacted_text = text
    redaction_count = 0
    for pattern, replacement in REDACTION_PATTERNS:
        redacted_text, count = pattern.subn(replacement, redacted_text)
        redaction_count += count

    was_truncated = len(redacted_text) > max_chars
    if was_truncated:
        redacted_text = redacted_text[:max_chars].rstrip() + "\n[TRUNCATED]"

    return ProviderRedactionResult(
        text=redacted_text,
        redaction_count=redaction_count,
        was_truncated=was_truncated,
    )
