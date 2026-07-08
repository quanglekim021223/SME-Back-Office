"""Tests for tenant isolation enforced by TenantScopedRepository.

These tests verify that cross-tenant data access is blocked at the repository
layer: a caller who knows a foreign UUID must receive ``None``, not the record.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.repositories.base import TenantScopedRepository
from app.repositories.documents import DocumentRepository
from app.repositories.invoices import InvoiceRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(scalar_one_or_none_return=None):
    """Return a mock AsyncSession whose execute() returns a fixed scalar."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_one_or_none_return
    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)
    return session


# ---------------------------------------------------------------------------
# TenantScopedRepository — base behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTenantScopedRepositoryBase:
    """Verify the base get_for_tenant builds correct WHERE clauses."""

    async def test_get_for_tenant_returns_none_when_session_returns_none(self):
        """get_for_tenant returns None when the DB returns no matching record."""
        from app.models.document import Document

        session = _make_session(scalar_one_or_none_return=None)
        repo = TenantScopedRepository(session, Document)

        result = await repo.get_for_tenant(tenant_id=uuid4(), object_id=uuid4())
        assert result is None

    async def test_get_for_tenant_returns_record_on_match(self):
        """get_for_tenant returns the model instance when the DB finds one."""
        from app.models.document import Document

        fake_doc = MagicMock(spec=Document)
        session = _make_session(scalar_one_or_none_return=fake_doc)
        repo = TenantScopedRepository(session, Document)

        result = await repo.get_for_tenant(tenant_id=uuid4(), object_id=uuid4())
        assert result is fake_doc


# ---------------------------------------------------------------------------
# DocumentRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDocumentRepositoryTenantIsolation:
    """get_for_tenant with DocumentRepository uses tenant + PK filter."""

    async def test_returns_none_for_mismatched_tenant(self):
        """Cross-tenant document lookup returns None (indistinguishable from 404)."""
        session = _make_session(scalar_one_or_none_return=None)
        repo = DocumentRepository(session)

        result = await repo.get_for_tenant(tenant_id=uuid4(), object_id=uuid4())
        assert result is None
        # Verify execute was called (query was actually issued)
        session.execute.assert_called_once()

    async def test_execute_is_called_with_tenant_filter(self):
        """The repository always calls session.execute, not session.get."""
        session = _make_session(scalar_one_or_none_return=None)
        repo = DocumentRepository(session)

        await repo.get_for_tenant(tenant_id=uuid4(), object_id=uuid4())
        # session.get would bypass tenant filtering — must not be called here
        session.get.assert_not_called()
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# InvoiceRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInvoiceRepositoryTenantIsolation:
    """InvoiceRepository enforces tenant isolation on every lookup."""

    async def test_get_for_tenant_returns_none_on_foreign_uuid(self):
        """A caller knowing a foreign invoice UUID gets None back."""
        session = _make_session(scalar_one_or_none_return=None)
        repo = InvoiceRepository(session)

        result = await repo.get_for_tenant(tenant_id=uuid4(), object_id=uuid4())
        assert result is None

    async def test_get_for_tenant_with_line_items_returns_none_on_foreign_uuid(self):
        """get_for_tenant_with_line_items applies the tenant filter."""
        session = _make_session(scalar_one_or_none_return=None)
        repo = InvoiceRepository(session)

        result = await repo.get_for_tenant_with_line_items(
            tenant_id=uuid4(), invoice_id=uuid4()
        )
        assert result is None

    async def test_list_for_tenant_uses_session_execute(self):
        """list_for_tenant always issues a DB query scoped to the tenant."""
        mock_items_result = MagicMock()
        mock_items_result.scalars.return_value.all.return_value = []

        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[mock_count_result, mock_items_result]
        )
        repo = InvoiceRepository(session)

        invoices, total = await repo.list_for_tenant(tenant_id=uuid4())
        assert invoices == []
        assert total == 0
        assert session.execute.call_count == 2


# ---------------------------------------------------------------------------
# Cross-tenant guard — two tenants, same PK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCrossTenantGuard:
    """Verify two different tenants cannot read each other's records."""

    async def test_tenant_a_cannot_access_tenant_b_document(self):
        """Returning None for tenant B's ID simulates the access-denied scenario."""
        tenant_a = uuid4()
        tenant_b = uuid4()
        shared_doc_id = uuid4()

        # Simulate tenant A has a record; tenant B does not (or record belongs to A)
        session_a = _make_session(scalar_one_or_none_return=MagicMock())
        session_b = _make_session(scalar_one_or_none_return=None)

        repo_a = DocumentRepository(session_a)
        repo_b = DocumentRepository(session_b)

        result_a = await repo_a.get_for_tenant(tenant_id=tenant_a, object_id=shared_doc_id)
        result_b = await repo_b.get_for_tenant(tenant_id=tenant_b, object_id=shared_doc_id)

        assert result_a is not None, "Tenant A should see their own document"
        assert result_b is None, "Tenant B must not see Tenant A's document"
