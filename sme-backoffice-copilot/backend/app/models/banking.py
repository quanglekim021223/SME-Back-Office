"""Bank account, statement import, and transaction ORM models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.document import Document, ProcessingRun


class BankAccountType(StrEnum):
    """Supported bank account families."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CREDIT_CARD = "credit_card"
    OTHER = "other"


class StatementImportStatus(StrEnum):
    """Statement import lifecycle states."""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class TransactionDirection(StrEnum):
    """Cash direction inferred from a bank transaction."""

    INFLOW = "inflow"
    OUTFLOW = "outflow"
    UNKNOWN = "unknown"


class TransactionStatus(StrEnum):
    """Transaction lifecycle states."""

    PENDING = "pending"
    POSTED = "posted"
    EXCLUDED = "excluded"


class BankAccount(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-owned bank account used to group imported statement transactions."""

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_identifier_hash",
            name="uq_bank_accounts_tenant_identifier_hash",
        ),
    )

    institution_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_type: Mapped[str] = mapped_column(
        String(64),
        default=BankAccountType.CHECKING.value,
        nullable=False,
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    masked_account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_identifier_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    statement_imports: Mapped[list[StatementImport]] = relationship(
        back_populates="bank_account",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="bank_account",
        cascade="all, delete-orphan",
    )


class StatementImport(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One imported bank statement file or feed batch."""

    __tablename__ = "statement_imports"

    bank_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_processing_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("processing_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=StatementImportStatus.PENDING.value,
        nullable=False,
    )
    source_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    statement_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    closing_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_count: Mapped[int] = mapped_column(default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    bank_account: Mapped[BankAccount] = relationship(back_populates="statement_imports")
    document: Mapped[Document | None] = relationship(back_populates="statement_imports")
    source_processing_run: Mapped[ProcessingRun | None] = relationship(
        back_populates="statement_imports"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="statement_import",
        cascade="all, delete-orphan",
    )


class Transaction(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured bank transaction parsed from a statement import."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "content_hash",
            name="uq_transactions_tenant_account_hash",
        ),
    )

    bank_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    statement_import_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("statement_imports.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=TransactionStatus.POSTED.value,
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(64),
        default=TransactionDirection.UNKNOWN.value,
        nullable=False,
    )
    posted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    running_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    external_transaction_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    bank_account: Mapped[BankAccount] = relationship(back_populates="transactions")
    statement_import: Mapped[StatementImport | None] = relationship(
        back_populates="transactions"
    )
