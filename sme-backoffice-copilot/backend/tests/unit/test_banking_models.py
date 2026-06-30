from app.models import (
    BankAccount,
    BankAccountType,
    StatementImport,
    StatementImportStatus,
    Transaction,
    TransactionDirection,
    TransactionStatus,
)
from app.models.base import Base


def test_banking_tables_are_registered_in_metadata() -> None:
    assert "bank_accounts" in Base.metadata.tables
    assert "statement_imports" in Base.metadata.tables
    assert "transactions" in Base.metadata.tables


def test_bank_account_columns_defaults_and_identifier_constraint() -> None:
    columns = BankAccount.__table__.c
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in BankAccount.__table__.constraints
        if constraint.name is not None
    }

    assert "tenant_id" in columns
    assert "institution_name" in columns
    assert "account_name" in columns
    assert columns["account_type"].default is not None
    assert columns["account_type"].default.arg == BankAccountType.CHECKING.value
    assert "currency" in columns
    assert "masked_account_number" in columns
    assert "account_identifier_hash" in columns
    assert columns["is_active"].default is not None
    assert columns["is_active"].default.arg is True
    assert constraints["uq_bank_accounts_tenant_identifier_hash"] == {
        "tenant_id",
        "account_identifier_hash",
    }


def test_statement_import_links_to_bank_account_document_and_processing_run() -> None:
    columns = StatementImport.__table__.c

    assert "tenant_id" in columns
    assert columns["bank_account_id"].index is True
    assert columns["bank_account_id"].nullable is False
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["bank_account_id"].foreign_keys
    } == {"bank_accounts"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["document_id"].foreign_keys
    } == {"documents"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["source_processing_run_id"].foreign_keys
    } == {"processing_runs"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == StatementImportStatus.PENDING.value
    assert "statement_start_date" in columns
    assert "statement_end_date" in columns
    assert "opening_balance" in columns
    assert "closing_balance" in columns
    assert "row_count" in columns
    assert "duplicate_count" in columns
    assert "metrics" in columns


def test_transaction_columns_defaults_and_links() -> None:
    columns = Transaction.__table__.c

    assert "tenant_id" in columns
    assert columns["bank_account_id"].index is True
    assert columns["bank_account_id"].nullable is False
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["bank_account_id"].foreign_keys
    } == {"bank_accounts"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["statement_import_id"].foreign_keys
    } == {"statement_imports"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == TransactionStatus.POSTED.value
    assert columns["direction"].default is not None
    assert columns["direction"].default.arg == TransactionDirection.UNKNOWN.value
    assert "posted_at" in columns
    assert "value_at" in columns
    assert "raw_description" in columns
    assert "normalized_description" in columns
    assert "counterparty_name" in columns
    assert "reference" in columns
    assert "amount" in columns
    assert columns["amount"].nullable is False
    assert "running_balance" in columns
    assert "content_hash" in columns
    assert columns["content_hash"].nullable is False
    assert "metadata" in columns


def test_transaction_has_tenant_account_content_hash_constraint() -> None:
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in Transaction.__table__.constraints
        if constraint.name is not None
    }

    assert constraints["uq_transactions_tenant_account_hash"] == {
        "tenant_id",
        "bank_account_id",
        "content_hash",
    }


def test_banking_enums_expose_stable_values() -> None:
    assert BankAccountType.CREDIT_CARD.value == "credit_card"
    assert StatementImportStatus.PARSED.value == "parsed"
    assert TransactionDirection.OUTFLOW.value == "outflow"
    assert TransactionStatus.EXCLUDED.value == "excluded"
