"""Invoice API schemas for list and detail endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.invoice import Invoice, InvoiceLineItem


class InvoiceLineItemResponse(BaseModel):
    """Response schema for a single invoice line item."""

    id: UUID
    invoice_id: UUID
    line_number: int
    description: str | None = None
    product_code: str | None = None
    quantity: Decimal | None = None
    unit_of_measure: str | None = None
    unit_price_amount: Decimal | None = None
    net_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    confidence: str | None = None

    @classmethod
    def from_model(cls, item: InvoiceLineItem) -> InvoiceLineItemResponse:
        """Build a response from an InvoiceLineItem ORM model."""

        return cls(
            id=item.id,
            invoice_id=item.invoice_id,
            line_number=item.line_number,
            description=item.description,
            product_code=item.product_code,
            quantity=item.quantity,
            unit_of_measure=item.unit_of_measure,
            unit_price_amount=item.unit_price_amount,
            net_amount=item.net_amount,
            tax_rate=item.tax_rate,
            tax_amount=item.tax_amount,
            total_amount=item.total_amount,
            currency=item.currency,
            confidence=item.confidence,
        )


class InvoiceSummaryResponse(BaseModel):
    """Compact invoice shape used by the invoice list API."""

    id: UUID
    tenant_id: UUID
    document_id: UUID | None = None
    version: int
    status: str
    direction: str
    invoice_number: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    subtotal_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    total_amount: Decimal | None = None
    confidence: str | None = None
    supersedes_invoice_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, invoice: Invoice) -> InvoiceSummaryResponse:
        """Build a list response from an Invoice ORM model."""

        return cls(
            id=invoice.id,
            tenant_id=invoice.tenant_id,
            document_id=invoice.document_id,
            version=invoice.version,
            status=invoice.status,
            direction=invoice.direction,
            invoice_number=invoice.invoice_number,
            supplier_name=invoice.supplier_name,
            customer_name=invoice.customer_name,
            issue_date=invoice.issue_date,
            due_date=invoice.due_date,
            currency=invoice.currency,
            subtotal_amount=invoice.subtotal_amount,
            tax_amount=invoice.tax_amount,
            total_amount=invoice.total_amount,
            confidence=invoice.confidence,
            supersedes_invoice_id=invoice.supersedes_invoice_id,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
        )


class InvoiceDetailResponse(InvoiceSummaryResponse):
    """Detailed invoice response including line items."""

    supplier_tax_id: str | None = None
    customer_tax_id: str | None = None
    notes: str | None = None
    source_processing_run_id: UUID | None = None
    line_items: list[InvoiceLineItemResponse] = Field(default_factory=list)

    @classmethod
    def from_model(cls, invoice: Invoice) -> InvoiceDetailResponse:
        """Build a detail response from an Invoice ORM model with line items."""

        summary = InvoiceSummaryResponse.from_model(invoice)
        return cls(
            **summary.model_dump(),
            supplier_tax_id=invoice.supplier_tax_id,
            customer_tax_id=invoice.customer_tax_id,
            notes=invoice.notes,
            source_processing_run_id=invoice.source_processing_run_id,
            line_items=[
                InvoiceLineItemResponse.from_model(item)
                for item in invoice.line_items
            ],
        )


class InvoiceListResponse(BaseModel):
    """Paginated invoice list response."""

    items: list[InvoiceSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
