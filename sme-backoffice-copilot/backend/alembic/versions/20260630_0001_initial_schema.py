"""Create initial application schema.

Revision ID: 20260630_0001
Revises:
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260630_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk_column() -> sa.Column:
    """Return the standard UUID primary key column."""

    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def tenant_column() -> sa.Column:
    """Return the standard tenant ownership column."""

    return sa.Column(
        "tenant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def timestamp_columns() -> tuple[sa.Column, sa.Column]:
    """Return standard created/updated timestamp columns."""

    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    """Apply schema changes."""

    op.create_table(
        "agent_definitions",
        sa.Column("agent_name", sa.String(length=128), nullable=False),
        sa.Column("agent_version", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_schema_ref", sa.String(length=255), nullable=True),
        sa.Column("output_schema_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "allowed_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "retry_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamp_columns(),
        uuid_pk_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_name",
            "agent_version",
            name="uq_agent_definitions_name_version",
        ),
    )

    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_actor_user_id",
        "audit_events",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_tenant_id",
        "audit_events",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "bank_accounts",
        sa.Column("institution_name", sa.String(length=255), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("account_type", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("masked_account_number", sa.String(length=64), nullable=True),
        sa.Column("account_identifier_hash", sa.String(length=128), nullable=True),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "account_identifier_hash",
            name="uq_bank_accounts_tenant_identifier_hash",
        ),
    )
    op.create_index(
        "ix_bank_accounts_tenant_id",
        "bank_accounts",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "categories",
        sa.Column(
            "parent_category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("category_type", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_code", sa.String(length=128), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_categories_tenant_slug"),
    )
    op.create_index(
        "ix_categories_parent_category_id",
        "categories",
        ["parent_category_id"],
        unique=False,
    )
    op.create_index(
        "ix_categories_tenant_id",
        "categories",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "documents",
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "content_hash",
            name="uq_documents_tenant_hash",
        ),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"], unique=False)

    op.create_table(
        "memberships",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "reconciliations",
        sa.Column(
            "supersedes_reconciliation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reconciliations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("match_type", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("invoice_total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("transaction_total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("difference_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("source_agent", sa.String(length=128), nullable=True),
        sa.Column("source_agent_version", sa.String(length=64), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliations_supersedes_reconciliation_id",
        "reconciliations",
        ["supersedes_reconciliation_id"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliations_tenant_id",
        "reconciliations",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "document_artifacts",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.String(length=1024), nullable=False),
        sa.Column("object_version", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_artifacts_document_id",
        "document_artifacts",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_artifacts_tenant_id",
        "document_artifacts",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "processing_runs",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("workflow_name", sa.String(length=128), nullable=False),
        sa.Column("workflow_version", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("config_version", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_runs_document_id",
        "processing_runs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_processing_runs_tenant_id",
        "processing_runs",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "invoices",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_processing_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=64), nullable=False),
        sa.Column("invoice_number", sa.String(length=128), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_tax_id", sa.String(length=128), nullable=True),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("customer_tax_id", sa.String(length=128), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("subtotal_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_document_id", "invoices", ["document_id"])
    op.create_index(
        "ix_invoices_source_processing_run_id",
        "invoices",
        ["source_processing_run_id"],
    )
    op.create_index(
        "ix_invoices_supersedes_invoice_id",
        "invoices",
        ["supersedes_invoice_id"],
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])

    op.create_table(
        "statement_imports",
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_processing_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=True),
        sa.Column("statement_start_date", sa.Date(), nullable=True),
        sa.Column("statement_end_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("opening_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("closing_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("parser_name", sa.String(length=128), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_statement_imports_bank_account_id",
        "statement_imports",
        ["bank_account_id"],
    )
    op.create_index(
        "ix_statement_imports_document_id",
        "statement_imports",
        ["document_id"],
    )
    op.create_index(
        "ix_statement_imports_source_processing_run_id",
        "statement_imports",
        ["source_processing_run_id"],
    )
    op.create_index(
        "ix_statement_imports_tenant_id",
        "statement_imports",
        ["tenant_id"],
    )

    op.create_table(
        "workflow_runs",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "processing_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow_name", sa.String(length=128), nullable=False),
        sa.Column("workflow_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("current_agent", sa.String(length=128), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_document_id", "workflow_runs", ["document_id"])
    op.create_index(
        "ix_workflow_runs_processing_run_id",
        "workflow_runs",
        ["processing_run_id"],
    )
    op.create_index("ix_workflow_runs_tenant_id", "workflow_runs", ["tenant_id"])

    op.create_table(
        "agent_step_executions",
        sa.Column(
            "workflow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_ref", sa.String(length=1024), nullable=True),
        sa.Column("output_ref", sa.String(length=1024), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_step_executions_agent_definition_id",
        "agent_step_executions",
        ["agent_definition_id"],
    )
    op.create_index(
        "ix_agent_step_executions_tenant_id",
        "agent_step_executions",
        ["tenant_id"],
    )
    op.create_index(
        "ix_agent_step_executions_workflow_run_id",
        "agent_step_executions",
        ["workflow_run_id"],
    )

    op.create_table(
        "insights",
        sa.Column(
            "source_workflow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_insight_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("insights.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("insight_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("estimated_impact_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("source_agent", sa.String(length=128), nullable=True),
        sa.Column("source_agent_version", sa.String(length=64), nullable=True),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_insights_source_workflow_run_id",
        "insights",
        ["source_workflow_run_id"],
    )
    op.create_index(
        "ix_insights_supersedes_insight_id",
        "insights",
        ["supersedes_insight_id"],
    )
    op.create_index("ix_insights_tenant_id", "insights", ["tenant_id"])

    op.create_table(
        "invoice_line_items",
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=64), nullable=True),
        sa.Column("unit_price_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("tax_rate", sa.Numeric(9, 4), nullable=True),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "invoice_id",
            "line_number",
            name="uq_invoice_line_items_invoice_line_number",
        ),
    )
    op.create_index(
        "ix_invoice_line_items_invoice_id",
        "invoice_line_items",
        ["invoice_id"],
    )
    op.create_index(
        "ix_invoice_line_items_tenant_id",
        "invoice_line_items",
        ["tenant_id"],
    )

    op.create_table(
        "transactions",
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "statement_import_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("statement_imports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=64), nullable=False),
        sa.Column("posted_at", sa.Date(), nullable=True),
        sa.Column("value_at", sa.Date(), nullable=True),
        sa.Column("raw_description", sa.Text(), nullable=True),
        sa.Column("normalized_description", sa.Text(), nullable=True),
        sa.Column("counterparty_name", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("running_balance", sa.Numeric(18, 2), nullable=True),
        sa.Column("external_transaction_id", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "bank_account_id",
            "content_hash",
            name="uq_transactions_tenant_account_hash",
        ),
    )
    op.create_index(
        "ix_transactions_bank_account_id",
        "transactions",
        ["bank_account_id"],
    )
    op.create_index(
        "ix_transactions_statement_import_id",
        "transactions",
        ["statement_import_id"],
    )
    op.create_index("ix_transactions_tenant_id", "transactions", ["tenant_id"])

    op.create_table(
        "agent_handoffs",
        sa.Column(
            "workflow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_step_execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_step_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_agent", sa.String(length=128), nullable=False),
        sa.Column("target_agent", sa.String(length=128), nullable=False),
        sa.Column("handoff_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload_ref", sa.String(length=1024), nullable=False),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("validation_status", sa.String(length=64), nullable=True),
        sa.Column(
            "policy_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_handoffs_source_step_execution_id",
        "agent_handoffs",
        ["source_step_execution_id"],
    )
    op.create_index(
        "ix_agent_handoffs_tenant_id",
        "agent_handoffs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_agent_handoffs_workflow_run_id",
        "agent_handoffs",
        ["workflow_run_id"],
    )

    op.create_table(
        "classification_proposals",
        sa.Column(
            "proposed_category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "invoice_line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoice_line_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classification_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("source_agent", sa.String(length=128), nullable=True),
        sa.Column("source_agent_version", sa.String(length=64), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "policy_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_proposals_invoice_id",
        "classification_proposals",
        ["invoice_id"],
    )
    op.create_index(
        "ix_classification_proposals_invoice_line_item_id",
        "classification_proposals",
        ["invoice_line_item_id"],
    )
    op.create_index(
        "ix_classification_proposals_proposed_category_id",
        "classification_proposals",
        ["proposed_category_id"],
    )
    op.create_index(
        "ix_classification_proposals_supersedes_proposal_id",
        "classification_proposals",
        ["supersedes_proposal_id"],
    )
    op.create_index(
        "ix_classification_proposals_tenant_id",
        "classification_proposals",
        ["tenant_id"],
    )
    op.create_index(
        "ix_classification_proposals_transaction_id",
        "classification_proposals",
        ["transaction_id"],
    )

    op.create_table(
        "invoice_field_evidence",
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoice_line_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=True),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "bounding_box", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("text_span", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_agent", sa.String(length=128), nullable=True),
        sa.Column("source_agent_version", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_field_evidence_artifact_id",
        "invoice_field_evidence",
        ["artifact_id"],
    )
    op.create_index(
        "ix_invoice_field_evidence_document_id",
        "invoice_field_evidence",
        ["document_id"],
    )
    op.create_index(
        "ix_invoice_field_evidence_invoice_id",
        "invoice_field_evidence",
        ["invoice_id"],
    )
    op.create_index(
        "ix_invoice_field_evidence_line_item_id",
        "invoice_field_evidence",
        ["line_item_id"],
    )
    op.create_index(
        "ix_invoice_field_evidence_tenant_id",
        "invoice_field_evidence",
        ["tenant_id"],
    )

    op.create_table(
        "reconciliation_allocations",
        sa.Column(
            "reconciliation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reconciliations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("allocation_method", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_allocations_invoice_id",
        "reconciliation_allocations",
        ["invoice_id"],
    )
    op.create_index(
        "ix_reconciliation_allocations_reconciliation_id",
        "reconciliation_allocations",
        ["reconciliation_id"],
    )
    op.create_index(
        "ix_reconciliation_allocations_tenant_id",
        "reconciliation_allocations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_reconciliation_allocations_transaction_id",
        "reconciliation_allocations",
        ["transaction_id"],
    )

    op.create_table(
        "review_tasks",
        sa.Column(
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workflow_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "classification_proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classification_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reconciliation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reconciliations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "insight_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("insights.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_agent", sa.String(length=128), nullable=True),
        sa.Column("source_agent_version", sa.String(length=64), nullable=True),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        tenant_column(),
        uuid_pk_column(),
        *timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_tasks_assigned_user_id",
        "review_tasks",
        ["assigned_user_id"],
    )
    op.create_index(
        "ix_review_tasks_classification_proposal_id",
        "review_tasks",
        ["classification_proposal_id"],
    )
    op.create_index("ix_review_tasks_document_id", "review_tasks", ["document_id"])
    op.create_index("ix_review_tasks_insight_id", "review_tasks", ["insight_id"])
    op.create_index("ix_review_tasks_invoice_id", "review_tasks", ["invoice_id"])
    op.create_index(
        "ix_review_tasks_reconciliation_id",
        "review_tasks",
        ["reconciliation_id"],
    )
    op.create_index(
        "ix_review_tasks_resolved_by_user_id",
        "review_tasks",
        ["resolved_by_user_id"],
    )
    op.create_index("ix_review_tasks_tenant_id", "review_tasks", ["tenant_id"])
    op.create_index(
        "ix_review_tasks_transaction_id",
        "review_tasks",
        ["transaction_id"],
    )
    op.create_index(
        "ix_review_tasks_workflow_run_id",
        "review_tasks",
        ["workflow_run_id"],
    )


def downgrade() -> None:
    """Revert schema changes."""

    for table_name in (
        "review_tasks",
        "reconciliation_allocations",
        "invoice_field_evidence",
        "classification_proposals",
        "agent_handoffs",
        "transactions",
        "invoice_line_items",
        "insights",
        "agent_step_executions",
        "workflow_runs",
        "statement_imports",
        "invoices",
        "processing_runs",
        "document_artifacts",
        "reconciliations",
        "memberships",
        "documents",
        "categories",
        "bank_accounts",
        "audit_events",
        "users",
        "organizations",
        "agent_definitions",
    ):
        op.drop_table(table_name)
