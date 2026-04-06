"""CLI management commands for LeadEnrich."""

import asyncio
import sys

from sqlalchemy import select

from app.auth.models import User
from app.auth.service import hash_password
from app.config import settings
from app.database import async_session


async def create_admin():
    """Create the initial admin user from environment variables."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.email == settings.admin_email)
        )
        if result.scalar_one_or_none():
            print(f"Admin user {settings.admin_email} already exists.")
            return

        user = User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            is_admin=True,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"Admin user created: {settings.admin_email}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        asyncio.run(create_admin())
    else:
        print("Usage: python manage.py create-admin")
        sys.exit(1)
