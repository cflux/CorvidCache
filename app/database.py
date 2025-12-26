"""
Database configuration and session management.

Provides async SQLAlchemy engine setup, session factory, and
FastAPI dependency for database access.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Create async database engine
engine = create_async_engine(settings.database_url, echo=False)

# Session factory for creating database sessions
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def get_db():
    """
    FastAPI dependency that provides a database session.

    Yields an async database session that is automatically closed
    after the request completes.

    Yields:
        AsyncSession: Database session for the current request.
    """
    async with async_session() as session:
        yield session


async def init_db():
    """
    Initialize the database by creating all tables.

    Called on application startup to ensure all model tables exist.
    Uses SQLAlchemy's create_all which is safe to call multiple times
    (only creates tables that don't exist).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
