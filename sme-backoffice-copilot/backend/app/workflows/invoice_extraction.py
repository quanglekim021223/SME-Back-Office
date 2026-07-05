"""Invoice extraction contracts and skeleton agents."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.extraction import (
    parse_invoice_metadata_group_payload,
    parse_invoice_table_group_payload,
    parse_invoice_totals_group_payload,
)
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
    OCR_FULL_TEXT_KEY,
    OCR_LAYOUT_REGIONS_KEY,
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
PROVIDER_EXTRACTION_ERRORS_KEY = "provider_extraction_errors"


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


async def run_llm_group_extraction_if_available(
    *,
    state: WorkflowState,
    context: AgentExecutionContext,
    agent_name: str,
    task_type: Any,
    schema_name: str,
    instruction: str,
    handoff: AgentHandoffEnvelope | None = None,
) -> dict[str, object] | AgentRunResult | None:
    """Run selected LLM provider for one invoice extraction group when wired."""

    from app.providers.errors import ProviderError
    from app.providers.llm import (
        LLMGenerationRequest,
        LLMProviderRunContext,
        LLMResponseFormat,
    )

    if context.provider_runtime is None or context.llm_provider is None:
        return None

    ocr_text = ocr_context_for_schema(state=state, schema_name=schema_name)
    if not ocr_text.strip():
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_LLM_INPUT_MISSING",
            error_message=f"{agent_name} requires OCR text before LLM extraction.",
        )

    try:
        invocation = await context.provider_runtime.generate_llm(
            provider=context.llm_provider,
            task_type=task_type,
            request=LLMGenerationRequest(
                messages=build_invoice_group_messages(
                    instruction=instruction,
                    ocr_text=ocr_text,
                    schema_name=schema_name,
                    handoff=handoff,
                ),
                response_format=LLMResponseFormat.JSON,
                response_schema_name=schema_name,
            ),
            context=LLMProviderRunContext(
                tenant_id=context.tenant_id,
                document_id=context.document_id,
                workflow_run_id=context.workflow_run_id,
                agent_name=agent_name,
                correlation_id=context.correlation_id,
            ),
            privacy_context=context.provider_privacy_context,
        )
    except ProviderError as exc:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_LLM_PROVIDER_FAILED",
            error_message=str(exc),
        )

    if invocation.result.structured_output is None:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_LLM_OUTPUT_MISSING",
            error_message=f"{agent_name} provider did not return structured JSON.",
        )
    return cast(dict[str, object], invocation.result.structured_output)


def build_invoice_group_messages(
    *,
    instruction: str,
    ocr_text: str,
    schema_name: str,
    handoff: AgentHandoffEnvelope | None,
) -> list[Any]:
    """Build compact provider-neutral messages for invoice group extraction."""

    from app.providers.llm import LLMMessage, LLMMessageRole

    correction_instruction = ""
    if handoff is not None and handoff.qa_error_signal is not None:
        correction_instruction = (
            f"\nCorrection signal:\n{handoff.qa_error_signal.model_dump_json()}"
        )

    return [
        LLMMessage(
            role=LLMMessageRole.SYSTEM,
            content=(
                "You extract one invoice data group for SME finance workflows. "
                f"Return JSON only matching schema {schema_name}. "
                "Do not include markdown, commentary, wrapper objects, or extra keys. "
                "Use null for unknown scalar fields and [] for unknown list fields. "
                "Dates must be ISO YYYY-MM-DD. If OCR uses MM-DD-YYYY, interpret it "
                "as US month-day-year."
            ),
        ),
        LLMMessage(
            role=LLMMessageRole.USER,
            content=(
                f"{instruction}\n\n"
                f"Return exactly this JSON shape:\n"
                f"{invoice_group_schema_example(schema_name)}\n\n"
                f"OCR text:\n{ocr_text}{correction_instruction}"
            ),
        ),
    ]


def invoice_group_schema_example(schema_name: str) -> str:
    """Return compact JSON examples for invoice extraction group prompts."""

    if schema_name == "invoice-metadata-group.v1":
        return (
            "{"
            '"schema_version":"invoice-metadata-group.v1",'
            '"extraction_status":"extracted",'
            '"invoice_number":null,'
            '"supplier_name":null,'
            '"supplier_tax_id":null,'
            '"customer_name":null,'
            '"customer_tax_id":null,'
            '"issue_date":null,'
            '"due_date":null,'
            '"currency":null,'
            '"evidence_refs":[],'
            '"confidence":"medium"'
            "}"
        )
    if schema_name == "invoice-table-group.v1":
        return (
            "{"
            '"schema_version":"invoice-table-group.v1",'
            '"extraction_status":"extracted",'
            '"line_items":[{'
            '"line_number":1,'
            '"description":null,'
            '"quantity":null,'
            '"unit_price":null,'
            '"tax_amount":null,'
            '"line_total":null,'
            '"evidence_refs":[],'
            '"confidence":"medium"'
            "}],"
            '"table_region_ref":null,'
            '"evidence_refs":[],'
            '"confidence":"medium"'
            "}"
        )
    if schema_name == "invoice-totals-group.v1":
        return (
            "{"
            '"schema_version":"invoice-totals-group.v1",'
            '"extraction_status":"extracted",'
            '"subtotal_amount":null,'
            '"tax_amount":null,'
            '"total_amount":null,'
            '"currency":null,'
            '"evidence_refs":[],'
            '"confidence":"medium"'
            "}"
        )
    return "{}"


def ocr_context_for_schema(
    *,
    state: WorkflowState,
    schema_name: str,
) -> str:
    """Return region-specific OCR context, falling back to full OCR text."""

    regions = state.scratchpad.get(OCR_LAYOUT_REGIONS_KEY)
    if isinstance(regions, dict):
        region_names = region_names_for_schema(schema_name)
        region_text = "\n\n".join(
            text
            for name in region_names
            if isinstance((region := regions.get(name)), dict)
            and isinstance((text := region.get("text")), str)
            and text.strip()
        )
        if region_text.strip():
            return region_text

    full_text = state.scratchpad.get(OCR_FULL_TEXT_KEY)
    return full_text if isinstance(full_text, str) else ""


def region_names_for_schema(schema_name: str) -> tuple[str, ...]:
    """Return OCR region names relevant to one invoice extraction group."""

    if schema_name == "invoice-metadata-group.v1":
        return ("header", "supplier", "bill_to", "ship_to")
    if schema_name == "invoice-table-group.v1":
        return ("line_item_table",)
    if schema_name == "invoice-totals-group.v1":
        return ("totals",)
    return ()


def contract_validation_failure_result(
    *,
    agent_name: str,
    exc: ValidationError,
) -> AgentRunResult:
    """Return a failed agent result for invalid provider contract output."""

    return AgentRunResult(
        status=AgentRunStatus.FAILED,
        confidence=ConfidenceLevel.HIGH,
        error_code="ERR_LLM_OUTPUT_SCHEMA",
        error_message=f"{agent_name} provider output failed schema validation: {exc}",
    )


def normalize_provider_invoice_group_payload(
    *,
    schema_name: str,
    payload: dict[str, object],
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Repair common LLM JSON shapes into the internal invoice group contracts."""

    if schema_name == "invoice-metadata-group.v1":
        return normalize_provider_metadata_payload(
            payload=payload,
            evidence_refs=evidence_refs,
        )
    if schema_name == "invoice-table-group.v1":
        return normalize_provider_table_payload(
            payload=payload,
            evidence_refs=evidence_refs,
        )
    if schema_name == "invoice-totals-group.v1":
        return normalize_provider_totals_payload(
            payload=payload,
            evidence_refs=evidence_refs,
        )
    return payload


def merge_provider_payload_with_ocr_fallback(
    *,
    schema_name: str,
    provider_payload: dict[str, object],
    fallback_payload: dict[str, object] | None,
) -> dict[str, object]:
    """Merge deterministic OCR fallback into normalized provider output."""

    if fallback_payload is None or "schema_version" not in provider_payload:
        return provider_payload

    merged = dict(provider_payload)
    if schema_name == "invoice-metadata-group.v1":
        fill_missing_keys(
            target=merged,
            source=fallback_payload,
            keys=(
                "invoice_number",
                "supplier_name",
                "supplier_tax_id",
                "customer_tax_id",
                "currency",
            ),
        )
        fallback_customer_name = fallback_payload.get("customer_name")
        if isinstance(fallback_customer_name, str) and fallback_customer_name.strip():
            merged["customer_name"] = fallback_customer_name

        # Prefer deterministic date parsing from OCR text because local LLMs often
        # reinterpret MM-DD-YYYY as DD-MM-YYYY.
        for key in ("issue_date", "due_date"):
            fallback_value = fallback_payload.get(key)
            if isinstance(fallback_value, str) and fallback_value.strip():
                merged[key] = fallback_value
        if (
            fallback_payload.get("due_date") is None
            and merged.get("due_date") == merged.get("issue_date")
        ):
            merged["due_date"] = None
        merge_evidence_refs(merged, fallback_payload)
        return merged

    if schema_name == "invoice-table-group.v1":
        line_items = merged.get("line_items")
        if not isinstance(line_items, list) or not line_items:
            merged["line_items"] = fallback_payload.get("line_items", [])
            merged["table_region_ref"] = fallback_payload.get("table_region_ref")
            merged["extraction_status"] = fallback_payload.get(
                "extraction_status",
                merged.get("extraction_status"),
            )
        merge_evidence_refs(merged, fallback_payload)
        return merged

    if schema_name == "invoice-totals-group.v1":
        fill_missing_keys(
            target=merged,
            source=fallback_payload,
            keys=("subtotal_amount", "tax_amount", "total_amount", "currency"),
        )
        if any(
            merged.get(key)
            for key in ("subtotal_amount", "tax_amount", "total_amount")
        ):
            merged["extraction_status"] = "extracted"
        merge_evidence_refs(merged, fallback_payload)
        return merged

    return provider_payload


def fill_missing_keys(
    *,
    target: dict[str, object],
    source: dict[str, object],
    keys: tuple[str, ...],
) -> None:
    """Copy source values only when the target value is empty."""

    for key in keys:
        target_value = target.get(key)
        source_value = source.get(key)
        if target_value in (None, "", []):
            target[key] = source_value


def merge_evidence_refs(
    target: dict[str, object],
    source: dict[str, object],
) -> None:
    """Merge evidence refs while preserving order."""

    existing = target.get("evidence_refs")
    incoming = source.get("evidence_refs")
    if not isinstance(existing, list):
        existing = []
    if not isinstance(incoming, list):
        incoming = []
    merged: list[object] = []
    for value in [*existing, *incoming]:
        if isinstance(value, str) and value not in merged:
            merged.append(value)
    target["evidence_refs"] = merged


def normalize_provider_metadata_payload(
    *,
    payload: dict[str, object],
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Map common model-created metadata wrappers to InvoiceMetadataGroup."""

    if "schema_version" in payload:
        return payload

    invoice_metadata = first_dict(payload, "invoiceMetadata", "metadata", "invoice")
    party = first_dict(payload, "party", "parties")
    issuer = first_dict(payload, "issuer", "supplier", "vendor")
    bill_to = first_dict(payload, "billTo", "customer", "client")
    if party:
        issuer = issuer or first_dict(party, "issuer", "supplier", "vendor")
        bill_to = bill_to or first_dict(party, "billTo", "customer", "client")

    source = invoice_metadata or payload
    recognized = any(
        key in payload
        for key in (
            "invoiceMetadata",
            "metadata",
            "invoice",
            "party",
            "parties",
            "issuer",
            "supplier",
            "vendor",
            "billTo",
            "customer",
            "client",
            "invoice_number",
            "invoiceNumber",
            "invoiceNo",
            "issue_date",
            "issueDate",
            "invoiceDate",
            "due_date",
            "dueDate",
            "currency",
        )
    )
    if not recognized:
        return payload

    supplier_source = issuer or source
    customer_source = bill_to or source
    extracted = any(
        value is not None
        for value in (
            first_string(source, "invoice_number", "invoiceNumber", "invoiceNo"),
            first_string(
                supplier_source,
                "supplier_name",
                "supplierName",
                "issuerName",
                "name",
            ),
            first_string(
                customer_source,
                "customer_name",
                "customerName",
                "billToName",
                "name",
            ),
            first_string(source, "issue_date", "issueDate", "invoiceDate", "date"),
            first_string(source, "due_date", "dueDate", "paymentDue"),
            first_string(source, "currency", "currencyCode"),
        )
    )
    return {
        "schema_version": "invoice-metadata-group.v1",
        "extraction_status": "extracted" if extracted else "placeholder",
        "invoice_number": first_string(
            source,
            "invoice_number",
            "invoiceNumber",
            "invoiceNo",
            "number",
        ),
        "supplier_name": first_string(
            supplier_source,
            "supplier_name",
            "supplierName",
            "issuerName",
            "vendorName",
            "name",
        ),
        "supplier_tax_id": first_string(
            supplier_source,
            "supplier_tax_id",
            "supplierTaxId",
            "issuerTaxId",
            "taxId",
        ),
        "customer_name": first_string(
            customer_source,
            "customer_name",
            "customerName",
            "billToName",
            "clientName",
            "name",
        ),
        "customer_tax_id": first_string(
            customer_source,
            "customer_tax_id",
            "customerTaxId",
            "billToTaxId",
            "taxId",
        ),
        "issue_date": first_string(
            source,
            "issue_date",
            "issueDate",
            "invoiceDate",
            "date",
        ),
        "due_date": first_string(source, "due_date", "dueDate", "paymentDue"),
        "currency": first_string(source, "currency", "currencyCode"),
        "evidence_refs": evidence_refs or ["llm:normalized:metadata"],
        "confidence": normalize_confidence_label(first_string(source, "confidence")),
    }


def normalize_provider_table_payload(
    *,
    payload: dict[str, object],
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Map common line item arrays to InvoiceTableGroup."""

    if "schema_version" in payload:
        return normalize_schema_conformant_table_payload(payload)

    items = first_list(payload, "line_items", "lineItems", "items", "rows")
    if items is None:
        return payload

    line_items: list[dict[str, object]] = []
    for index, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        description = first_string(item, "description", "name", "item", "service")
        quantity = first_string_or_number(item, "quantity", "qty")
        unit_price = first_string_or_number(
            item,
            "unit_price",
            "unitPrice",
            "price",
            "rate",
        )
        line_total = first_string_or_number(
            item,
            "line_total",
            "lineTotal",
            "amount",
            "total",
        )
        if not any([description, quantity, unit_price, line_total]):
            continue
        line_items.append(
            {
                "line_number": index,
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "tax_amount": first_string_or_number(
                    item,
                    "tax_amount",
                    "taxAmount",
                    "tax",
                ),
                "line_total": line_total,
                "evidence_refs": [f"llm:normalized:table:row:{index}"],
                "confidence": normalize_confidence_label(
                    first_string(item, "confidence")
                ),
            }
        )

    return {
        "schema_version": "invoice-table-group.v1",
        "extraction_status": "extracted" if line_items else "placeholder",
        "line_items": line_items,
        "table_region_ref": "llm:normalized:table" if line_items else None,
        "evidence_refs": evidence_refs or ["llm:normalized:table"],
        "confidence": "medium" if line_items else "unknown",
    }


def normalize_provider_totals_payload(
    *,
    payload: dict[str, object],
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    """Map common totals keys to InvoiceTotalsGroup."""

    if "schema_version" in payload:
        return normalize_schema_conformant_totals_payload(payload)

    totals = first_dict(payload, "totals", "summary") or payload
    recognized = any(
        key in payload
        for key in (
            "totals",
            "summary",
            "subtotal_amount",
            "subtotalAmount",
            "invoice_subtotal",
            "subtotal",
            "tax_amount",
            "taxAmount",
            "sales_tax",
            "salesTax",
            "tax",
            "total_amount",
            "totalAmount",
            "grand_total",
            "grandTotal",
            "total",
            "amountDue",
            "currency",
        )
    )
    if not recognized:
        return payload

    subtotal_amount = first_string_or_number(
        totals,
        "subtotal_amount",
        "subtotalAmount",
        "invoice_subtotal",
        "subtotal",
    )
    tax_amount = first_string_or_number(
        totals,
        "tax_amount",
        "taxAmount",
        "sales_tax",
        "salesTax",
        "tax",
    )
    total_amount = first_string_or_number(
        totals,
        "total_amount",
        "totalAmount",
        "grand_total",
        "grandTotal",
        "total",
        "amountDue",
    )
    currency = first_string(totals, "currency", "currencyCode")
    extracted = any([subtotal_amount, tax_amount, total_amount, currency])
    return {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "extracted" if extracted else "placeholder",
        "subtotal_amount": subtotal_amount,
        "tax_amount": tax_amount,
        "total_amount": total_amount,
        "currency": currency,
        "evidence_refs": evidence_refs or ["llm:normalized:totals"],
        "confidence": normalize_confidence_label(first_string(totals, "confidence")),
    }


def normalize_schema_conformant_table_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    """Normalize scalar types inside an already schema-shaped table payload."""

    normalized = dict(payload)
    line_items = normalized.get("line_items")
    if isinstance(line_items, list):
        normalized_items: list[object] = []
        for item in line_items:
            if not isinstance(item, dict):
                normalized_items.append(item)
                continue
            normalized_item = dict(item)
            for key in (
                "description",
                "quantity",
                "unit_price",
                "tax_amount",
                "line_total",
            ):
                if key in normalized_item:
                    normalized_item[key] = scalar_to_string_or_none(
                        normalized_item[key]
                    )
            normalized_items.append(normalized_item)
        normalized["line_items"] = normalized_items
    return normalized


def normalize_schema_conformant_totals_payload(
    payload: dict[str, object],
) -> dict[str, object]:
    """Normalize scalar types inside an already schema-shaped totals payload."""

    normalized = dict(payload)
    for key in ("subtotal_amount", "tax_amount", "total_amount", "currency"):
        if key in normalized:
            normalized[key] = scalar_to_string_or_none(normalized[key])
    return normalized


def first_dict(value: dict[str, object], *keys: str) -> dict[str, object] | None:
    """Return first nested dict matching any key."""

    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, dict):
            return cast(dict[str, object], candidate)
    return None


def first_list(value: dict[str, object], *keys: str) -> list[object] | None:
    """Return first nested list matching any key."""

    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            return candidate
    return None


def first_string(value: dict[str, object], *keys: str) -> str | None:
    """Return first non-empty string matching any key."""

    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def first_string_or_number(value: dict[str, object], *keys: str) -> str | None:
    """Return first scalar string/number matching any key as a string."""

    for key in keys:
        normalized = scalar_to_string_or_none(value.get(key))
        if normalized is not None:
            return normalized
    return None


def scalar_to_string_or_none(value: object) -> str | None:
    """Normalize model scalar values to contract string-or-null fields."""

    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        cleaned = stripped.replace("$", "").replace(",", "")
        return format_decimal_string(cleaned) or cleaned
    if isinstance(value, int | float):
        return format_decimal_string(str(value))
    return None


def format_decimal_string(value: str) -> str | None:
    """Format numeric strings as two-decimal financial values when possible."""

    try:
        decimal_value = Decimal(value)
    except InvalidOperation:
        return None
    return str(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_confidence_label(value: str | None) -> str:
    """Normalize arbitrary model confidence labels to internal enum values."""

    if value is None:
        return "medium"
    normalized = value.strip().lower()
    if normalized in {"unknown", "low", "medium", "high"}:
        return normalized
    if normalized in {"certain", "confident"}:
        return "high"
    return "medium"


def record_provider_extraction_error(
    *,
    state: WorkflowState,
    agent_name: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    """Record provider extraction failures for later review/debug metadata.

    Also emits a non-retryable BLOCKING QA signal so the QA validation agent
    routes the workflow to REVIEW_REQUIRED when a provider produces invalid or
    missing output.  This covers two distinct failure paths:

    * Provider call fails (ProviderError / missing structured output).
    * Provider output passes the LLM call but fails Pydantic schema validation.
    """

    errors = state.scratchpad.setdefault(PROVIDER_EXTRACTION_ERRORS_KEY, [])
    if not isinstance(errors, list):
        errors = []
        state.scratchpad[PROVIDER_EXTRACTION_ERRORS_KEY] = errors
    errors.append(
        {
            "agent_name": agent_name,
            "error_code": error_code,
            "error_message": error_message,
        }
    )

    signal_code = (
        error_code
        if error_code is not None and error_code.strip()
        else "ERR_PROVIDER_EXTRACTION_FAILED"
    )
    state.qa_error_signals.append(
        QAErrorSignal(
            code=signal_code,
            severity=QAErrorSeverity.BLOCKING,
            message=(
                f"{agent_name} provider extraction failed and requires human review: "
                f"{error_message or 'unknown error'}"
            ),
            source_agent=agent_name,
            correction_target=None,
            retryable=False,
        )
    )


def ocr_text_fallback_payload(
    *,
    state: WorkflowState,
    schema_name: str,
    handoff: AgentHandoffEnvelope | None,
) -> dict[str, object] | None:
    """Build a group payload from OCR text when provider JSON is unusable."""

    ocr_text = ocr_context_for_schema(state=state, schema_name=schema_name)
    evidence_refs = get_handoff_evidence_refs(handoff)

    if schema_name == "invoice-metadata-group.v1":
        return parse_invoice_metadata_group_payload(
            ocr_text=ocr_text,
            evidence_refs=evidence_refs,
        )
    if schema_name == "invoice-table-group.v1":
        return parse_invoice_table_group_payload(
            ocr_text=ocr_text,
            evidence_refs=evidence_refs,
        )
    if schema_name == "invoice-totals-group.v1":
        return parse_invoice_totals_group_payload(
            ocr_text=ocr_text,
            evidence_refs=evidence_refs,
        )
    return None


def provider_task_type(value: str) -> Any:
    """Return provider task enum without importing provider package at module load."""

    from app.providers.routing import ProviderTaskType

    return ProviderTaskType(value)


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

        provider_payload = await run_llm_group_extraction_if_available(
            state=state,
            context=context,
            agent_name=METADATA_EXTRACTOR_AGENT,
            task_type=provider_task_type("invoice_metadata_extraction"),
            schema_name="invoice-metadata-group.v1",
            instruction="Extract only invoice metadata and party fields.",
            handoff=handoff,
        )
        if isinstance(provider_payload, AgentRunResult):
            record_provider_extraction_error(
                state=state,
                agent_name=METADATA_EXTRACTOR_AGENT,
                error_code=provider_payload.error_code,
                error_message=provider_payload.error_message,
            )
            provider_payload = ocr_text_fallback_payload(
                state=state,
                schema_name="invoice-metadata-group.v1",
                handoff=handoff,
            )

        if provider_payload is None:
            group = InvoiceMetadataGroup(
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
        else:
            provider_payload = normalize_provider_invoice_group_payload(
                schema_name="invoice-metadata-group.v1",
                payload=provider_payload,
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
            provider_payload = merge_provider_payload_with_ocr_fallback(
                schema_name="invoice-metadata-group.v1",
                provider_payload=provider_payload,
                fallback_payload=ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-metadata-group.v1",
                    handoff=handoff,
                ),
            )
            try:
                group = InvoiceMetadataGroup.model_validate(provider_payload)
            except ValidationError as exc:
                record_provider_extraction_error(
                    state=state,
                    agent_name=METADATA_EXTRACTOR_AGENT,
                    error_code="ERR_LLM_OUTPUT_SCHEMA",
                    error_message=str(exc),
                )
                fallback_payload = ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-metadata-group.v1",
                    handoff=handoff,
                )
                if fallback_payload is None:
                    return contract_validation_failure_result(
                        agent_name=METADATA_EXTRACTOR_AGENT,
                        exc=exc,
                    )
                group = InvoiceMetadataGroup.model_validate(fallback_payload)

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
            confidence=group.confidence,
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

        provider_payload = await run_llm_group_extraction_if_available(
            state=state,
            context=context,
            agent_name=TABLE_EXTRACTOR_AGENT,
            task_type=provider_task_type("invoice_table_extraction"),
            schema_name="invoice-table-group.v1",
            instruction="Extract only invoice line-item table rows.",
            handoff=handoff,
        )
        if isinstance(provider_payload, AgentRunResult):
            record_provider_extraction_error(
                state=state,
                agent_name=TABLE_EXTRACTOR_AGENT,
                error_code=provider_payload.error_code,
                error_message=provider_payload.error_message,
            )
            provider_payload = ocr_text_fallback_payload(
                state=state,
                schema_name="invoice-table-group.v1",
                handoff=handoff,
            )

        if provider_payload is None:
            group = InvoiceTableGroup(
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
        else:
            provider_payload = normalize_provider_invoice_group_payload(
                schema_name="invoice-table-group.v1",
                payload=provider_payload,
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
            provider_payload = merge_provider_payload_with_ocr_fallback(
                schema_name="invoice-table-group.v1",
                provider_payload=provider_payload,
                fallback_payload=ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-table-group.v1",
                    handoff=handoff,
                ),
            )
            try:
                group = InvoiceTableGroup.model_validate(provider_payload)
            except ValidationError as exc:
                record_provider_extraction_error(
                    state=state,
                    agent_name=TABLE_EXTRACTOR_AGENT,
                    error_code="ERR_LLM_OUTPUT_SCHEMA",
                    error_message=str(exc),
                )
                fallback_payload = ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-table-group.v1",
                    handoff=handoff,
                )
                if fallback_payload is None:
                    return contract_validation_failure_result(
                        agent_name=TABLE_EXTRACTOR_AGENT,
                        exc=exc,
                    )
                group = InvoiceTableGroup.model_validate(fallback_payload)

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
            confidence=group.confidence,
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

        provider_payload = await run_llm_group_extraction_if_available(
            state=state,
            context=context,
            agent_name=TOTALS_EXTRACTOR_AGENT,
            task_type=provider_task_type("invoice_totals_extraction"),
            schema_name="invoice-totals-group.v1",
            instruction="Extract only invoice subtotal, tax, total, and currency.",
            handoff=handoff,
        )
        if isinstance(provider_payload, AgentRunResult):
            record_provider_extraction_error(
                state=state,
                agent_name=TOTALS_EXTRACTOR_AGENT,
                error_code=provider_payload.error_code,
                error_message=provider_payload.error_message,
            )
            provider_payload = ocr_text_fallback_payload(
                state=state,
                schema_name="invoice-totals-group.v1",
                handoff=handoff,
            )

        if provider_payload is None:
            group = InvoiceTotalsGroup(
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
        else:
            provider_payload = normalize_provider_invoice_group_payload(
                schema_name="invoice-totals-group.v1",
                payload=provider_payload,
                evidence_refs=get_handoff_evidence_refs(handoff),
            )
            provider_payload = merge_provider_payload_with_ocr_fallback(
                schema_name="invoice-totals-group.v1",
                provider_payload=provider_payload,
                fallback_payload=ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-totals-group.v1",
                    handoff=handoff,
                ),
            )
            try:
                group = InvoiceTotalsGroup.model_validate(provider_payload)
            except ValidationError as exc:
                record_provider_extraction_error(
                    state=state,
                    agent_name=TOTALS_EXTRACTOR_AGENT,
                    error_code="ERR_LLM_OUTPUT_SCHEMA",
                    error_message=str(exc),
                )
                fallback_payload = ocr_text_fallback_payload(
                    state=state,
                    schema_name="invoice-totals-group.v1",
                    handoff=handoff,
                )
                if fallback_payload is None:
                    return contract_validation_failure_result(
                        agent_name=TOTALS_EXTRACTOR_AGENT,
                        exc=exc,
                    )
                group = InvoiceTotalsGroup.model_validate(fallback_payload)

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
            confidence=group.confidence,
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

        financial_signals = build_financial_review_signals(state)
        if financial_signals:
            state.qa_error_signals.extend(financial_signals)

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


def build_financial_review_signals(state: WorkflowState) -> list[QAErrorSignal]:
    """Validate the assembled invoice draft and emit review-required QA signals."""

    draft_payload = state.scratchpad.get(ASSEMBLED_INVOICE_DRAFT_KEY)
    if draft_payload is None:
        return []

    try:
        draft = AssembledInvoiceDraft.model_validate(draft_payload)
    except ValidationError:
        return []

    from app.validation.deterministic import validate_invoice_arithmetic

    result = validate_invoice_arithmetic(draft.groups)
    if result.passed:
        return []

    signals: list[QAErrorSignal] = []
    for issue in result.issues:
        signals.append(
            QAErrorSignal(
                code=issue.code,
                severity=QAErrorSeverity.ERROR,
                message=issue.message,
                source_agent=QA_VALIDATION_AGENT,
                expected_value=issue.expected_value,
                observed_value=issue.observed_value,
                context={
                    "validator_name": result.validator_name,
                    "field_path": issue.field_path,
                    "metrics": result.metrics,
                    **issue.context,
                },
                retryable=False,
            )
        )
    return signals
