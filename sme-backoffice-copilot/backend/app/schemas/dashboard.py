"""Dashboard API schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FinancialMetricResponse(BaseModel):
    """Single dashboard financial metric."""

    available: bool
    amount: Decimal | None = None
    currency: str | None = None
    by_currency: dict[str, Decimal] = Field(default_factory=dict)
    transaction_count: int = Field(ge=0, default=0)
    account_count: int = Field(ge=0, default=0)
    period_start: date | None = None
    period_end: date | None = None
    source: str


class DashboardFinancialSummaryResponse(BaseModel):
    """Finance summary used by the local operator dashboard."""

    cash_position: FinancialMetricResponse
    inflow: FinancialMetricResponse
    outflow: FinancialMetricResponse
    generated_at: datetime
