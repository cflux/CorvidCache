"""
Database configuration and session management.

Provides async SQLAlchemy engine setup, session factory, and
FastAPI dependency for database access.
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

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


async def run_migrations(conn):
    """
    Run database migrations for schema changes.

    Adds new columns to existing tables if they don't exist.
    """
    # Migration: Add source column to downloads table
    try:
        await conn.execute(text("SELECT source FROM downloads LIMIT 1"))
    except Exception:
        logger.info("Adding 'source' column to downloads table...")
        await conn.execute(text("ALTER TABLE downloads ADD COLUMN source VARCHAR(50)"))

    # Migration: Add source column to downloaded_videos table
    try:
        await conn.execute(text("SELECT source FROM downloaded_videos LIMIT 1"))
    except Exception:
        logger.info("Adding 'source' column to downloaded_videos table...")
        await conn.execute(text("ALTER TABLE downloaded_videos ADD COLUMN source VARCHAR(50)"))

    # Migration: Add keep_last_n column to subscriptions table
    try:
        await conn.execute(text("SELECT keep_last_n FROM subscriptions LIMIT 1"))
    except Exception:
        logger.info("Adding 'keep_last_n' column to subscriptions table...")
        await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN keep_last_n INTEGER"))

    # Migration: Add include_members column to subscriptions table
    try:
        await conn.execute(text("SELECT include_members FROM subscriptions LIMIT 1"))
    except Exception:
        logger.info("Adding 'include_members' column to subscriptions table...")
        await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN include_members BOOLEAN DEFAULT 1"))


async def init_db():
    """
    Initialize the database by creating all tables.

    Called on application startup to ensure all model tables exist.
    Uses SQLAlchemy's create_all which is safe to call multiple times
    (only creates tables that don't exist).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Run migrations for existing tables
        await run_migrations(conn)
