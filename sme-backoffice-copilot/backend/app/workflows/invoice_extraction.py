"""Invoice extraction contracts and skeleton agents."""

from __future__ import annotations

from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.agents import (
    AgentDefinitionSpec,
    AgentExecutionContext,
    AgentRunResult,
    AgentRunStatus,
)
from app.workflows.contracts import (
    AgentHandoffEnvelope,
    ConfidenceLevel,
    CorrectionAction,
    HandoffType,
    QACorrectionTarget,
    QAErrorSeverity,
    QAErrorSignal,
    WorkflowStage,
    WorkflowState,
)
from app.workflows.document_preparation import (
    METADATA_EXTRACTOR_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    build_control_handoff,
    validate_agent_context,
)

INVOICE_ASSEMBLY_NODE = "invoice_assembly"
QA_VALIDATION_AGENT = "qa_validator"
CLASSIFICATION_AGENT = "classification_agent"

INVOICE_METADATA_GROUP_KEY = "invoice_metadata_group"
INVOICE_TABLE_GROUP_KEY = "invoice_table_group"
INVOICE_TOTALS_GROUP_KEY = "invoice_totals_group"
ASSEMBLED_INVOICE_DRAFT_KEY = "assembled_invoice_draft"


class InvoiceExtractionStatus(StrEnum):
    """Lifecycle status for invoice extraction group outputs."""

    PLACEHOLDER = "placeholder"
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    FAILED = "failed"


class InvoiceMetadataGroup(BaseModel):
    """Structured contract for invoice header and party metadata."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "invoice-metadata-group.v1"
    extraction_status: InvoiceExtractionStatus = InvoiceExtractionStatus.PLACEHOLDER
    invoice_number: str | None = None
    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    customer_name: str | None = None
    customer_tax_id: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class InvoiceLineItemCandidate(BaseModel):
    """Structured contract for one invoice table row candidate."""

    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1)
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    tax_amount: str | None = None
    line_total: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class InvoiceTableGroup(BaseModel):
    """Structured contract for invoice line-item table extraction."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "invoice-table-group.v1"
    extraction_status: InvoiceExtractionStatus = InvoiceExtractionStatus.PLACEHOLDER
    line_items: list[InvoiceLineItemCandidate] = Field(default_factory=list)
    table_region_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class InvoiceTotalsGroup(BaseModel):
    """Structured contract for invoice subtotal, tax, and total fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "invoice-totals-group.v1"
    extraction_status: InvoiceExtractionStatus = InvoiceExtractionStatus.PLACEHOLDER
    subtotal_amount: str | None = None
    tax_amount: str | None = None
    total_amount: str | None = None
    currency: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class InvoiceExtractionGroups(BaseModel):
    """Container for the three independently extracted invoice groups."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "invoice-extraction-groups.v1"
    metadata: InvoiceMetadataGroup | None = None
    table: InvoiceTableGroup | None = None
    totals: InvoiceTotalsGroup | None = None

    @property
    def missing_group_names(self) -> list[str]:
        """Return group names that have not been produced yet."""

        missing: list[str] = []
        if self.metadata is None:
            missing.append("metadata")
        if self.table is None:
            missing.append("table")
        if self.totals is None:
            missing.append("totals")
        return missing


class AssembledInvoiceDraft(BaseModel):
    """Placeholder assembled invoice draft produced before QA validation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "assembled-invoice-draft.v1"
    document_id: UUID
    groups: InvoiceExtractionGroups
    assembly_status: InvoiceExtractionStatus
    missing_group_names: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


def model_to_payload(model: BaseModel) -> dict[str, object]:
    """Serialize a pydantic model into a JSON-compatible workflow payload."""

    return cast(dict[str, object], model.model_dump(mode="json"))


def get_handoff_evidence_refs(
    handoff: AgentHandoffEnvelope | None,
) -> list[str]:
    """Return evidence refs from an incoming handoff, if present."""

    if handoff is None:
        return []
    return handoff.evidence_refs


def build_data_handoff(
    *,
    state: WorkflowState,
    source_agent: str,
    target_agent: str,
    stage: WorkflowStage,
    payload: dict[str, object],
    evidence_refs: list[str] | None = None,
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN,
) -> AgentHandoffEnvelope:
    """Build a standard data handoff for invoice extraction outputs."""

    return AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        source_agent=source_agent,
        target_agent=target_agent,
        handoff_type=HandoffType.DATA,
        stage=stage,
        payload=payload,
        evidence_refs=evidence_refs or [],
        confidence=confidence,
    )


def extraction_stage_for_agent(agent_name: str) -> WorkflowStage:
    """Return the extraction stage owned by an extractor agent."""

    if agent_name == METADATA_EXTRACTOR_AGENT:
        return WorkflowStage.METADATA_EXTRACTION
    if agent_name == TABLE_EXTRACTOR_AGENT:
        return WorkflowStage.TABLE_EXTRACTION
    if agent_name == TOTALS_EXTRACTOR_AGENT:
        return WorkflowStage.TOTALS_EXTRACTION
    return WorkflowStage.QA_VALIDATION


def build_targeted_correction_handoff(
    *,
    state: WorkflowState,
    signal: QAErrorSignal,
) -> AgentHandoffEnvelope:
    """Route a structured QA error signal to its target extractor agent."""

    if signal.correction_target is None:
        raise ValueError("QA error signal requires a correction target.")

    target = signal.correction_target
    return AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        source_agent=QA_VALIDATION_AGENT,
        target_agent=target.target_agent,
        handoff_type=HandoffType.CORRECTION,
        stage=extraction_stage_for_agent(target.target_agent),
        payload={
            "qa_error_signal": model_to_payload(signal),
            "field_path": target.field_path,
            "instruction": target.instruction,
            "action": target.action.value,
        },
        evidence_refs=target.evidence_refs,
        confidence=ConfidenceLevel.HIGH,
        qa_error_signal=signal,
    )


def collect_invoice_groups(state: WorkflowState) -> InvoiceExtractionGroups:
    """Collect invoice extraction groups from workflow scratchpad."""

    metadata_payload = state.scratchpad.get(INVOICE_METADATA_GROUP_KEY)
    table_payload = state.scratchpad.get(INVOICE_TABLE_GROUP_KEY)
    totals_payload = state.scratchpad.get(INVOICE_TOTALS_GROUP_KEY)
    return InvoiceExtractionGroups(
        metadata=(
            InvoiceMetadataGroup.model_validate(metadata_payload)
            if metadata_payload is not None
            else None
        ),
        table=(
            InvoiceTableGroup.model_validate(table_payload)
            if table_payload is not None
            else None
        ),
        totals=(
            InvoiceTotalsGroup.model_validate(totals_payload)
            if totals_payload is not None
            else None
        ),
    )


class MetadataExtractorAgent:
    """Skeleton agent for invoice metadata extraction."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned metadata extractor definition."""

        return AgentDefinitionSpec(
            name=METADATA_EXTRACTOR_AGENT,
            version="0.1.0",
            description="Extracts invoice header and party metadata placeholders.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="invoice-metadata-group.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Produce a placeholder metadata group and route to invoice assembly."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=METADATA_EXTRACTOR_AGENT,
        )
        if context_error is not None:
            return context_error

        group = InvoiceMetadataGroup(
            evidence_refs=get_handoff_evidence_refs(handoff),
        )
        group_payload = model_to_payload(group)
        state.scratchpad[INVOICE_METADATA_GROUP_KEY] = group_payload
        output: dict[str, object] = {
            "group_name": "metadata",
            "metadata": group_payload,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=METADATA_EXTRACTOR_AGENT,
                    target_agent=INVOICE_ASSEMBLY_NODE,
                    stage=WorkflowStage.INVOICE_ASSEMBLY,
                    payload=output,
                    evidence_refs=group.evidence_refs,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
        )


class TableExtractorAgent:
    """Skeleton agent for invoice line-item table extraction."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned table extractor definition."""

        return AgentDefinitionSpec(
            name=TABLE_EXTRACTOR_AGENT,
            version="0.1.0",
            description="Extracts invoice line-item table placeholders.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="invoice-table-group.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Produce a placeholder table group and route to invoice assembly."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=TABLE_EXTRACTOR_AGENT,
        )
        if context_error is not None:
            return context_error

        group = InvoiceTableGroup(
            evidence_refs=get_handoff_evidence_refs(handoff),
        )
        group_payload = model_to_payload(group)
        state.scratchpad[INVOICE_TABLE_GROUP_KEY] = group_payload
        output: dict[str, object] = {
            "group_name": "table",
            "table": group_payload,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=TABLE_EXTRACTOR_AGENT,
                    target_agent=INVOICE_ASSEMBLY_NODE,
                    stage=WorkflowStage.INVOICE_ASSEMBLY,
                    payload=output,
                    evidence_refs=group.evidence_refs,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
            metrics={"line_item_count": len(group.line_items)},
        )


class TotalsExtractorAgent:
    """Skeleton agent for invoice subtotal, tax, and total extraction."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned totals extractor definition."""

        return AgentDefinitionSpec(
            name=TOTALS_EXTRACTOR_AGENT,
            version="0.1.0",
            description="Extracts invoice subtotal, tax, and total placeholders.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="invoice-totals-group.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Produce a placeholder totals group and route to invoice assembly."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=TOTALS_EXTRACTOR_AGENT,
        )
        if context_error is not None:
            return context_error

        group = InvoiceTotalsGroup(
            evidence_refs=get_handoff_evidence_refs(handoff),
        )
        group_payload = model_to_payload(group)
        state.scratchpad[INVOICE_TOTALS_GROUP_KEY] = group_payload
        output: dict[str, object] = {
            "group_name": "totals",
            "totals": group_payload,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=TOTALS_EXTRACTOR_AGENT,
                    target_agent=INVOICE_ASSEMBLY_NODE,
                    stage=WorkflowStage.INVOICE_ASSEMBLY,
                    payload=output,
                    evidence_refs=group.evidence_refs,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
        )


class InvoiceAssemblyNode:
    """Skeleton node that assembles invoice extraction groups into one draft."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned invoice assembly node definition."""

        return AgentDefinitionSpec(
            name=INVOICE_ASSEMBLY_NODE,
            version="0.1.0",
            description="Combines metadata, table, and totals groups into a draft.",
            input_schema_ref="invoice-extraction-groups.v1",
            output_schema_ref="assembled-invoice-draft.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Assemble available invoice groups and route to QA validation."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=INVOICE_ASSEMBLY_NODE,
        )
        if context_error is not None:
            return context_error

        groups = collect_invoice_groups(state)
        missing_group_names = groups.missing_group_names
        assembly_status = (
            InvoiceExtractionStatus.EXTRACTED
            if not missing_group_names
            else InvoiceExtractionStatus.PARTIAL
        )
        draft = AssembledInvoiceDraft(
            document_id=state.document_id,
            groups=groups,
            assembly_status=assembly_status,
            missing_group_names=missing_group_names,
        )
        draft_payload = model_to_payload(draft)
        state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY] = draft_payload
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=draft_payload,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=INVOICE_ASSEMBLY_NODE,
                    target_agent=QA_VALIDATION_AGENT,
                    stage=WorkflowStage.QA_VALIDATION,
                    payload={"assembled_invoice_draft": draft_payload},
                    confidence=ConfidenceLevel.UNKNOWN,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
            metrics={"missing_group_count": len(missing_group_names)},
        )


class QAValidationAgent:
    """Skeleton QA agent with targeted self-correction routing."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned QA validation agent definition."""

        return AgentDefinitionSpec(
            name=QA_VALIDATION_AGENT,
            version="0.1.0",
            description="Validates invoice draft placeholders and routes corrections.",
            input_schema_ref="assembled-invoice-draft.v1",
            output_schema_ref="qa-validation-result.v1",
            allowed_tools=["arithmetic_validator"],
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Route retryable QA signals or pass the draft to classification."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=QA_VALIDATION_AGENT,
        )
        if context_error is not None:
            return context_error

        correction_signals = [
            signal
            for signal in state.qa_error_signals
            if signal.retryable and signal.correction_target is not None
        ]
        if correction_signals:
            correction_handoffs = [
                build_targeted_correction_handoff(state=state, signal=signal)
                for signal in correction_signals
            ]
            return AgentRunResult(
                status=AgentRunStatus.RETRY_REQUESTED,
                output={
                    "validation_status": "correction_required",
                    "qa_error_count": len(correction_signals),
                },
                handoffs=correction_handoffs,
                qa_error_signals=correction_signals,
                confidence=ConfidenceLevel.HIGH,
            )

        non_retryable_signals = [
            signal
            for signal in state.qa_error_signals
            if not signal.retryable
            or signal.severity in {QAErrorSeverity.BLOCKING, QAErrorSeverity.ERROR}
        ]
        if non_retryable_signals:
            return AgentRunResult(
                status=AgentRunStatus.REVIEW_REQUIRED,
                output={
                    "validation_status": "review_required",
                    "qa_error_count": len(non_retryable_signals),
                },
                qa_error_signals=non_retryable_signals,
                confidence=ConfidenceLevel.HIGH,
            )

        validation_output: dict[str, object] = {
            "validation_status": "passed_placeholder",
            "qa_error_count": 0,
            "validated_draft_ref": ASSEMBLED_INVOICE_DRAFT_KEY,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=validation_output,
            handoffs=[
                build_control_handoff(
                    state=state,
                    source_agent=QA_VALIDATION_AGENT,
                    target_agent=CLASSIFICATION_AGENT,
                    stage=WorkflowStage.CLASSIFICATION,
                    payload=validation_output,
                    confidence=ConfidenceLevel.UNKNOWN,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
        )


def create_total_amount_correction_signal(
    *,
    expected_value: object,
    observed_value: object,
    evidence_refs: list[str] | None = None,
) -> QAErrorSignal:
    """Create a standard targeted correction signal for invoice totals."""

    return QAErrorSignal(
        code="ERR_LOGIC_MATH",
        severity=QAErrorSeverity.ERROR,
        message="Extracted invoice total does not match subtotal plus tax.",
        source_agent=QA_VALIDATION_AGENT,
        correction_target=QACorrectionTarget(
            target_agent=TOTALS_EXTRACTOR_AGENT,
            action=CorrectionAction.RE_EXTRACT_FIELD,
            field_path="invoice.total_amount",
            evidence_refs=evidence_refs or [],
            instruction="Re-check only the invoice total_amount field.",
        ),
        expected_value=expected_value,
        observed_value=observed_value,
        retryable=True,
    )
