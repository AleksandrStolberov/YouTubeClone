from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker as _async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

async_engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

async_sessionmaker = _async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker() as session:
        yield session
