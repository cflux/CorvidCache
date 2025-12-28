"""
Pydantic schemas for API request/response validation.

These schemas define the structure of data sent to and received from
the API endpoints, providing automatic validation and serialization.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models import DownloadStatus


class DownloadOptions(BaseModel):
    """
    Configuration options for a video download.

    Attributes:
        format: yt-dlp format selector (e.g., "best", "bestvideo[height<=1080]+bestaudio").
        output_format: Desired output container format.
        output_template: yt-dlp output template with variables like %(title)s.
        subtitles: Whether to download subtitles.
        subtitle_langs: List of subtitle language codes to download.
        embed_thumbnail: Whether to embed thumbnail in the output file.
        embed_metadata: Whether to embed metadata in the output file.
    """
    format: str = "best"
    output_format: str = "mp4"
    output_template: str = "%(channel)s/%(upload_date)s_%(title)s.%(ext)s"
    subtitles: bool = False
    subtitle_langs: list[str] = Field(default_factory=lambda: ["en"])
    embed_thumbnail: bool = False
    embed_metadata: bool = True


class DownloadCreate(BaseModel):
    """Request to create a new download."""
    url: str
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class DownloadBatchCreate(BaseModel):
    """Request to create multiple downloads with shared options."""
    urls: list[str]
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class DownloadResponse(BaseModel):
    """API response containing download details."""
    id: int
    video_id: Optional[str]
    url: str
    title: Optional[str]
    thumbnail: Optional[str]
    source: Optional[str]
    status: DownloadStatus
    progress: float
    speed: Optional[str]
    eta: Optional[str]
    output_path: Optional[str]
    error_message: Optional[str]
    options: dict
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class ExtractRequest(BaseModel):
    """Request to extract metadata from a URL."""
    url: str


class ExtractResponse(BaseModel):
    """
    Response from URL extraction.

    Indicates whether the URL points to a video, playlist, or channel,
    along with basic metadata.
    """
    type: str  # "video", "playlist", "channel"
    title: str
    video_id: Optional[str] = None
    count: Optional[int] = None
    uploader: Optional[str] = None


class PlaylistRequest(BaseModel):
    """Request to fetch playlist/channel contents."""
    url: str


class PlaylistEntry(BaseModel):
    """
    Single video entry within a playlist or channel.

    Attributes:
        video_id: Platform-specific video identifier.
        title: Video title.
        duration: Duration in seconds.
        duration_string: Human-readable duration (e.g., "10:30").
        thumbnail: URL to video thumbnail.
        uploader: Channel/uploader name.
        already_downloaded: Whether this video exists in download history.
        members_only: Whether this video requires channel membership.
    """
    video_id: str
    title: str
    duration: Optional[int] = None
    duration_string: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    already_downloaded: bool = False
    members_only: bool = False


class PlaylistResponse(BaseModel):
    """Response containing playlist/channel contents."""
    title: str
    entries: list[PlaylistEntry]
    total_count: int


class FormatInfo(BaseModel):
    """Available format/quality option for a video."""
    format_id: str
    ext: str
    resolution: Optional[str]
    filesize: Optional[int]
    format_note: Optional[str]


class FormatsResponse(BaseModel):
    """Response containing available formats for a video."""
    formats: list[FormatInfo]


class FileInfo(BaseModel):
    """Information about a downloaded file."""
    name: str
    size: int
    modified: datetime
    thumbnail: Optional[str] = None
    source: Optional[str] = None


class SubscriptionCreate(BaseModel):
    """Request to create a new subscription."""
    url: str
    name: Optional[str] = None
    check_interval_hours: int = 24
    options: DownloadOptions = Field(default_factory=DownloadOptions)
    keep_last_n: Optional[int] = None
    include_members: bool = True


class SubscriptionResponse(BaseModel):
    """API response containing subscription details."""
    id: int
    url: str
    name: str
    check_interval_hours: int
    enabled: bool
    options: dict
    last_checked: Optional[datetime]
    last_video_count: int
    created_at: datetime
    keep_last_n: Optional[int] = None
    include_members: bool = True

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    """Request to update subscription settings."""
    name: Optional[str] = None
    check_interval_hours: Optional[int] = None
    enabled: Optional[bool] = None
    options: Optional[DownloadOptions] = None
    keep_last_n: Optional[int] = None
    include_members: Optional[bool] = None
