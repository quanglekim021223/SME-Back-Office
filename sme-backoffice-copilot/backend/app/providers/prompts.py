"""Versioned prompt registry for provider-backed agents."""

from __future__ import annotations

from collections.abc import Mapping
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field

from app.providers.errors import ProviderPromptError
from app.providers.llm import LLMMessage, LLMMessageRole


class PromptMessageTemplate(BaseModel):
    """One provider-neutral prompt message template."""

    model_config = ConfigDict(extra="forbid")

    role: LLMMessageRole
    template: str = Field(min_length=1)


class PromptSpec(BaseModel):
    """Versioned prompt definition stored in the local prompt registry."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    response_schema_name: str | None = None
    messages: list[PromptMessageTemplate] = Field(min_length=1)
    required_variables: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    def render_messages(self, variables: Mapping[str, object]) -> list[LLMMessage]:
        """Render this prompt into concrete LLM messages."""

        missing_variables = [
            variable
            for variable in self.required_variables
            if variable not in variables or variables[variable] is None
        ]
        if missing_variables:
            raise ProviderPromptError(
                "Missing prompt variables for "
                f"{self.prompt_id}@{self.version}: {', '.join(missing_variables)}"
            )

        return [
            LLMMessage(
                role=message.role,
                content=render_template(message.template, variables),
            )
            for message in self.messages
        ]


class PromptRenderResult(BaseModel):
    """Rendered prompt payload ready to become an LLM generation request."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    response_schema_name: str | None = None
    messages: list[LLMMessage] = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class PromptRegistry:
    """In-memory registry for versioned agent prompts."""

    def __init__(self, prompts: list[PromptSpec] | None = None) -> None:
        self._prompts: dict[tuple[str, str], PromptSpec] = {}
        for prompt in prompts or []:
            self.register(prompt)

    def register(self, prompt: PromptSpec) -> None:
        """Register or replace one prompt spec."""

        self._prompts[(prompt.prompt_id, prompt.version)] = prompt

    def get(self, prompt_id: str, version: str | None = None) -> PromptSpec:
        """Return a prompt by ID and optional version."""

        if version is not None:
            prompt = self._prompts.get((prompt_id, version))
            if prompt is None:
                raise ProviderPromptError(f"Prompt not found: {prompt_id}@{version}")
            return prompt

        candidates = [
            prompt
            for (candidate_prompt_id, _), prompt in self._prompts.items()
            if candidate_prompt_id == prompt_id
        ]
        if not candidates:
            raise ProviderPromptError(f"Prompt not found: {prompt_id}")
        return sorted(candidates, key=lambda prompt: prompt.version)[-1]

    def render(
        self,
        *,
        prompt_id: str,
        variables: Mapping[str, object],
        version: str | None = None,
    ) -> PromptRenderResult:
        """Render one registered prompt."""

        prompt = self.get(prompt_id=prompt_id, version=version)
        return PromptRenderResult(
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            response_schema_name=prompt.response_schema_name,
            messages=prompt.render_messages(variables),
            metadata=prompt.metadata,
        )

    def list_prompts(self) -> list[PromptSpec]:
        """Return all registered prompts sorted by prompt ID and version."""

        return [
            self._prompts[key]
            for key in sorted(self._prompts, key=lambda item: (item[0], item[1]))
        ]


def render_template(template: str, variables: Mapping[str, object]) -> str:
    """Render a prompt template using Python format placeholders."""

    missing_placeholders = [
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name and field_name not in variables
    ]
    if missing_placeholders:
        raise ProviderPromptError(
            "Missing prompt variables: " + ", ".join(sorted(missing_placeholders))
        )
    return template.format(**{key: str(value) for key, value in variables.items()})


def build_default_prompt_registry() -> PromptRegistry:
    """Build the default local prompt registry."""

    return PromptRegistry(
        prompts=[
            PromptSpec(
                prompt_id="invoice.metadata_extraction",
                version="0.1.0",
                description="Extract invoice header, parties, dates, and currency.",
                response_schema_name="invoice-metadata-group.v1",
                required_variables=["ocr_text"],
                messages=[
                    PromptMessageTemplate(
                        role=LLMMessageRole.SYSTEM,
                        template=(
                            "You extract only invoice metadata. Return JSON that "
                            "matches the requested schema. Do not invent missing "
                            "fields; use null when uncertain."
                        ),
                    ),
                    PromptMessageTemplate(
                        role=LLMMessageRole.USER,
                        template="OCR text:\n{ocr_text}",
                    ),
                ],
            ),
            PromptSpec(
                prompt_id="invoice.table_extraction",
                version="0.1.0",
                description="Extract invoice line items from table-like OCR text.",
                response_schema_name="invoice-table-group.v1",
                required_variables=["ocr_text"],
                messages=[
                    PromptMessageTemplate(
                        role=LLMMessageRole.SYSTEM,
                        template=(
                            "You extract invoice line items. Return one item per "
                            "source row and include evidence references when known."
                        ),
                    ),
                    PromptMessageTemplate(
                        role=LLMMessageRole.USER,
                        template="Invoice OCR text:\n{ocr_text}",
                    ),
                ],
            ),
            PromptSpec(
                prompt_id="invoice.totals_extraction",
                version="0.1.0",
                description="Extract invoice subtotal, tax, total, and currency.",
                response_schema_name="invoice-totals-group.v1",
                required_variables=["ocr_text"],
                messages=[
                    PromptMessageTemplate(
                        role=LLMMessageRole.SYSTEM,
                        template=(
                            "You extract invoice totals only. Return JSON and keep "
                            "amounts as decimal strings."
                        ),
                    ),
                    PromptMessageTemplate(
                        role=LLMMessageRole.USER,
                        template="Invoice OCR text:\n{ocr_text}",
                    ),
                ],
            ),
            PromptSpec(
                prompt_id="invoice.classification",
                version="0.1.0",
                description=(
                    "Classify an assembled invoice into an accounting category."
                ),
                response_schema_name="classification-draft.v1",
                required_variables=["invoice_json"],
                messages=[
                    PromptMessageTemplate(
                        role=LLMMessageRole.SYSTEM,
                        template=(
                            "You classify SME invoice records. Prefer conservative "
                            "outputs and explain the category rationale."
                        ),
                    ),
                    PromptMessageTemplate(
                        role=LLMMessageRole.USER,
                        template="Assembled invoice JSON:\n{invoice_json}",
                    ),
                ],
            ),
        ]
    )


DEFAULT_PROMPT_REGISTRY = build_default_prompt_registry()
