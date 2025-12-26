"""
SQLAlchemy database models.

This module defines the database schema for the application including
downloads, download history, subscriptions, and settings.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import String, Float, DateTime, JSON, Enum, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DownloadStatus(str, PyEnum):
    """
    Enumeration of possible download states.

    States:
        QUEUED: Download is waiting to start.
        FETCHING_INFO: Extracting video metadata from URL.
        DOWNLOADING: Actively downloading the video.
        COMPLETED: Download finished successfully.
        FAILED: Download encountered an error.
        CANCELLED: Download was cancelled by user.
    """
    QUEUED = "queued"
    FETCHING_INFO = "fetching_info"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Download(Base):
    """
    Represents a video download task.

    Tracks the full lifecycle of a download from queue to completion,
    including progress updates and error handling.

    Attributes:
        id: Primary key.
        video_id: Platform-specific video identifier (e.g., YouTube video ID).
        url: Original URL submitted for download.
        title: Video title (populated after metadata extraction).
        thumbnail: URL to video thumbnail image.
        status: Current download state (see DownloadStatus).
        progress: Download progress percentage (0-100).
        speed: Current download speed (e.g., "1.5 MiB/s").
        eta: Estimated time remaining (e.g., "00:05:23").
        output_path: Relative path to downloaded file.
        error_message: Error description if download failed.
        options: JSON blob of download options used.
        created_at: Timestamp when download was queued.
        completed_at: Timestamp when download finished.
    """
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(500))
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    thumbnail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[DownloadStatus] = mapped_column(
        Enum(DownloadStatus), default=DownloadStatus.QUEUED
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    speed: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    eta: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DownloadedVideo(Base):
    """
    Historical record of successfully downloaded videos.

    Used to track which videos have been downloaded previously,
    enabling "Select New Only" functionality when browsing playlists.

    Attributes:
        id: Primary key.
        video_id: Platform-specific video identifier (unique).
        title: Video title at time of download.
        channel: Channel/uploader name.
        downloaded_at: Timestamp of successful download.
        file_path: Path to file (may be outdated if file moved/deleted).
    """
    __tablename__ = "downloaded_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    channel: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)


class Subscription(Base):
    """
    Channel or playlist subscription for automatic monitoring.

    Stores configuration for periodically checking channels/playlists
    for new videos and automatically downloading them.

    Attributes:
        id: Primary key.
        url: Channel or playlist URL to monitor.
        name: Display name for the subscription.
        check_interval_hours: How often to check for new videos.
        enabled: Whether automatic checking is active.
        options: JSON blob of download options to use.
        last_checked: Timestamp of last check.
        last_video_count: Number of videos found on last check.
        created_at: Timestamp when subscription was created.
    """
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200))
    check_interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_video_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Settings(Base):
    """
    Key-value store for application settings.

    Stores persistent settings like saved download options.

    Attributes:
        id: Primary key.
        key: Setting name (unique).
        value: JSON blob containing the setting value.
    """
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
