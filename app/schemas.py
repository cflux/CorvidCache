from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models import DownloadStatus


class DownloadOptions(BaseModel):
    format: str = "best"
    output_format: str = "mp4"  # mp4, mkv, webm, mp3, m4a, opus, flac
    output_template: str = "%(channel)s/%(upload_date)s_%(title)s.%(ext)s"
    subtitles: bool = False
    subtitle_langs: list[str] = Field(default_factory=lambda: ["en"])
    embed_thumbnail: bool = False
    embed_metadata: bool = True


class DownloadCreate(BaseModel):
    url: str
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class DownloadBatchCreate(BaseModel):
    urls: list[str]
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class DownloadResponse(BaseModel):
    id: int
    video_id: Optional[str]
    url: str
    title: Optional[str]
    thumbnail: Optional[str]
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
    url: str


class ExtractResponse(BaseModel):
    type: str  # "video", "playlist", "channel"
    title: str
    video_id: Optional[str] = None
    count: Optional[int] = None
    uploader: Optional[str] = None


class PlaylistRequest(BaseModel):
    url: str


class PlaylistEntry(BaseModel):
    video_id: str
    title: str
    duration: Optional[int] = None
    duration_string: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    already_downloaded: bool = False
    members_only: bool = False


class PlaylistResponse(BaseModel):
    title: str
    entries: list[PlaylistEntry]
    total_count: int


class FormatInfo(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str]
    filesize: Optional[int]
    format_note: Optional[str]


class FormatsResponse(BaseModel):
    formats: list[FormatInfo]


class FileInfo(BaseModel):
    name: str
    size: int
    modified: datetime
    thumbnail: Optional[str] = None


class SubscriptionCreate(BaseModel):
    url: str
    name: Optional[str] = None
    check_interval_hours: int = 24
    options: DownloadOptions = Field(default_factory=DownloadOptions)


class SubscriptionResponse(BaseModel):
    id: int
    url: str
    name: str
    check_interval_hours: int
    enabled: bool
    options: dict
    last_checked: Optional[datetime]
    last_video_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    check_interval_hours: Optional[int] = None
    enabled: Optional[bool] = None
    options: Optional[DownloadOptions] = None
