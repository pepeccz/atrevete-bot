"""
Database connection module - Async SQLAlchemy engine and session management.

Provides async database engine and session factory for the application.
All database operations should use get_async_session() context manager.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config import get_settings

# Get settings
settings = get_settings()

# Create async engine with connection pooling
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for SQL query logging during development
    pool_size=10,  # Number of connections to maintain in the pool
    max_overflow=20,  # Maximum number of connections to create beyond pool_size
    pool_pre_ping=True,  # Verify connections before using them
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Usage:
        async with get_async_session() as session:
            result = await session.execute(select(Customer))
            customers = result.scalars().all()

    Yields:
        AsyncSession: Database session instance
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database by creating all tables.

    NOTE: In production, use Alembic migrations instead.
    This function is useful for testing or initial setup.
    """
    from database.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close database engine and all connections.

    Call this during application shutdown.
    """
    await engine.dispose()
