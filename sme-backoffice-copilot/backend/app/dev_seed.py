"""Seed local development identity data.

This module is intentionally small and deterministic. It creates the demo
organizations and user referenced by the frontend dev placeholders so local UI
flows can exercise tenant-owned tables without manual SQL.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from app.core.db import async_session_factory
from app.models.organization import Organization
from app.models.user import Membership, User

DEMO_COFFEE_ID = UUID("00000000-0000-4000-8000-000000000001")
DEMO_RETAIL_ID = UUID("00000000-0000-4000-8000-000000000002")
DEV_USER_ID = UUID("00000000-0000-4000-8000-000000000101")
DEMO_COFFEE_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000001001")
DEMO_RETAIL_MEMBERSHIP_ID = UUID("00000000-0000-4000-8000-000000001002")


async def seed_dev_data() -> None:
    """Create demo organizations, a dev user, and memberships."""

    async with async_session_factory() as session:
        await session.execute(
            insert(Organization)
            .values(
                [
                    {
                        "id": DEMO_COFFEE_ID,
                        "is_active": True,
                        "name": "Demo Coffee Co.",
                        "slug": "demo-coffee",
                    },
                    {
                        "id": DEMO_RETAIL_ID,
                        "is_active": True,
                        "name": "Demo Retail Ltd.",
                        "slug": "demo-retail",
                    },
                ]
            )
            .on_conflict_do_update(
                index_elements=[Organization.id],
                set_={
                    "is_active": True,
                    "name": insert(Organization).excluded.name,
                    "slug": insert(Organization).excluded.slug,
                },
            )
        )
        await session.execute(
            insert(User)
            .values(
                id=DEV_USER_ID,
                display_name="Dev Finance User",
                email="dev.finance@example.local",
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={
                    "display_name": "Dev Finance User",
                    "email": "dev.finance@example.local",
                    "is_active": True,
                },
            )
        )
        await session.execute(
            insert(Membership)
            .values(
                [
                    {
                        "id": DEMO_COFFEE_MEMBERSHIP_ID,
                        "role": "member",
                        "status": "active",
                        "tenant_id": DEMO_COFFEE_ID,
                        "user_id": DEV_USER_ID,
                    },
                    {
                        "id": DEMO_RETAIL_MEMBERSHIP_ID,
                        "role": "member",
                        "status": "active",
                        "tenant_id": DEMO_RETAIL_ID,
                        "user_id": DEV_USER_ID,
                    },
                ]
            )
            .on_conflict_do_update(
                constraint="uq_memberships_tenant_user",
                set_={
                    "role": "member",
                    "status": "active",
                },
            )
        )
        await session.commit()


def main() -> None:
    """Run the local development seed command."""

    asyncio.run(seed_dev_data())


if __name__ == "__main__":
    main()
