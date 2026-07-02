"""Fixture loader for deterministic AI and parser outputs."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from app.models.banking import (
    BankAccountType,
    StatementImportStatus,
    TransactionDirection,
    TransactionStatus,
)
from app.workflows.contracts import ConfidenceLevel
from app.workflows.invoice_extraction import InvoiceExtractionGroups

FIXTURE_ROOT = Path(__file__).parent / "data"


class FixtureKind(StrEnum):
    """Fixture families available to tests and local replay utilities."""

    INVOICE_EXTRACTION = "invoice_extraction"
    STATEMENT_PARSING = "statement_parsing"


class FixtureLoadError(RuntimeError):
    """Base error for fixture loading failures."""


class FixtureNotFoundError(FixtureLoadError):
    """Raised when a requested fixture file does not exist."""


class InvoiceExtractionFixture(BaseModel):
    """Fixture containing repeatable invoice OCR text and extraction output."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "fixture.invoice-extraction.v1"
    fixture_name: str = Field(min_length=1)
    source_document_type: str = "invoice"
    ocr_text: str = Field(min_length=1)
    extraction_groups: InvoiceExtractionGroups
    expected_validation: dict[str, object] = Field(default_factory=dict)


class StatementBankAccountFixture(BaseModel):
    """Fixture bank account payload compatible with BankAccount fields."""

    model_config = ConfigDict(extra="forbid")

    institution_name: str = Field(min_length=1)
    account_name: str | None = None
    account_type: BankAccountType = BankAccountType.CHECKING
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    masked_account_number: str | None = None
    account_identifier_hash: str | None = None


class StatementImportFixture(BaseModel):
    """Fixture statement import payload compatible with StatementImport fields."""

    model_config = ConfigDict(extra="forbid")

    status: StatementImportStatus = StatementImportStatus.PARSED
    source_filename: str | None = None
    statement_start_date: date | None = None
    statement_end_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    row_count: int = Field(default=0, ge=0)
    duplicate_count: int = Field(default=0, ge=0)


class StatementTransactionFixture(BaseModel):
    """Fixture transaction payload compatible with Transaction fields."""

    model_config = ConfigDict(extra="forbid")

    status: TransactionStatus = TransactionStatus.POSTED
    direction: TransactionDirection
    posted_at: date | None = None
    value_at: date | None = None
    raw_description: str | None = None
    normalized_description: str | None = None
    counterparty_name: str | None = None
    reference: str | None = None
    amount: Decimal
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    running_balance: Decimal | None = None
    external_transaction_id: str | None = None
    content_hash: str = Field(min_length=1)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    metadata: dict[str, object] = Field(default_factory=dict)


class StatementParsingFixture(BaseModel):
    """Fixture containing repeatable bank statement parser output."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "fixture.statement-parsing.v1"
    fixture_name: str = Field(min_length=1)
    source_document_type: str = "bank_statement"
    bank_account: StatementBankAccountFixture
    statement_import: StatementImportFixture
    transactions: list[StatementTransactionFixture] = Field(min_length=1)
    expected_metrics: dict[str, object] = Field(default_factory=dict)


def load_json_fixture(
    *,
    kind: FixtureKind,
    name: str,
) -> dict[str, object]:
    """Load a JSON fixture payload by kind and fixture name."""

    path = fixture_path(kind=kind, name=name)
    if not path.exists():
        raise FixtureNotFoundError(f"Fixture does not exist: {kind.value}/{name}")
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def load_invoice_extraction_fixture(
    name: str = "sample_invoice_extraction",
) -> InvoiceExtractionFixture:
    """Load and validate an invoice extraction fixture."""

    return InvoiceExtractionFixture.model_validate(
        load_json_fixture(kind=FixtureKind.INVOICE_EXTRACTION, name=name)
    )


def load_statement_parsing_fixture(
    name: str = "sample_statement_parsing",
) -> StatementParsingFixture:
    """Load and validate a statement parsing fixture."""

    return StatementParsingFixture.model_validate(
        load_json_fixture(kind=FixtureKind.STATEMENT_PARSING, name=name)
    )


def list_fixture_names(kind: FixtureKind) -> list[str]:
    """Return available fixture names for one fixture kind."""

    directory = fixture_directory(kind)
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def fixture_path(
    *,
    kind: FixtureKind,
    name: str,
) -> Path:
    """Return the safe filesystem path for one fixture."""

    ensure_safe_fixture_name(name)
    return fixture_directory(kind) / f"{name}.json"


def fixture_directory(kind: FixtureKind) -> Path:
    """Return the directory that stores one fixture kind."""

    return FIXTURE_ROOT / kind.value


def ensure_safe_fixture_name(name: str) -> None:
    """Reject fixture names that could escape the fixture root."""

    if not name or Path(name).name != name or Path(name).suffix:
        raise FixtureLoadError(f"Invalid fixture name: {name!r}")
