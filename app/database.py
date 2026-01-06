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

    # Migration: Add thumbnail column to downloaded_videos table
    try:
        await conn.execute(text("SELECT thumbnail FROM downloaded_videos LIMIT 1"))
    except Exception:
        logger.info("Adding 'thumbnail' column to downloaded_videos table...")
        await conn.execute(text("ALTER TABLE downloaded_videos ADD COLUMN thumbnail VARCHAR(500)"))

    # Migration: Add title_filter column to subscriptions table
    try:
        await conn.execute(text("SELECT title_filter FROM subscriptions LIMIT 1"))
    except Exception:
        logger.info("Adding 'title_filter' column to subscriptions table...")
        await conn.execute(text("ALTER TABLE subscriptions ADD COLUMN title_filter VARCHAR(500)"))


async def ensure_default_presets():
    """Ensure default output path preset exists."""
    from app.models import Settings

    async with async_session() as db:
        result = await db.execute(
            text("SELECT value FROM settings WHERE key = 'output_path_presets'")
        )
        row = result.fetchone()

        default_template = "%(channel)s/%(upload_date)s_%(title)s.%(ext)s"
        default_preset = {"name": "Default", "template": default_template}

        if row is None:
            # No presets exist, create with default
            import json
            await db.execute(
                text("INSERT INTO settings (key, value) VALUES (:key, :value)"),
                {"key": "output_path_presets", "value": json.dumps({"presets": [default_preset]})}
            )
            await db.commit()
            logger.info("Created default output path preset")
        else:
            # Check if default preset exists
            import json
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            presets = data.get("presets", [])
            if not any(p.get("name") == "Default" for p in presets):
                # Add default preset at the beginning
                presets.insert(0, default_preset)
                await db.execute(
                    text("UPDATE settings SET value = :value WHERE key = 'output_path_presets'"),
                    {"value": json.dumps({"presets": presets})}
                )
                await db.commit()
                logger.info("Added default output path preset")


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

    # Ensure default presets exist
    await ensure_default_presets()
