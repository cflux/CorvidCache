from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import String, Float, DateTime, JSON, Enum, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DownloadStatus(str, PyEnum):
    QUEUED = "queued"
    FETCHING_INFO = "fetching_info"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Download(Base):
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
    __tablename__ = "downloaded_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    channel: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)


class Subscription(Base):
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
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
