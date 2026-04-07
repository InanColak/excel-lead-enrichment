import asyncio

from sqlalchemy import func, select

from app.auth.models import User
from app.auth.service import hash_password
from app.config import settings
from app.database import async_session


async def seed_admin() -> None:
    """Seed an admin user if the users table is empty."""
    async with async_session() as session:
        result = await session.execute(select(func.count()).select_from(User))
        count = result.scalar_one()

        if count > 0:
            print("Users exist, skipping seed")
            return

        if not settings.admin_email or not settings.admin_password:
            print("ADMIN_EMAIL or ADMIN_PASSWORD not set, skipping seed")
            return

        admin = User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            is_admin=True,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        print(f"Seeded admin user: {settings.admin_email}")


def main() -> None:
    asyncio.run(seed_admin())


if __name__ == "__main__":
    main()
