import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yt_dlp

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File

logger = logging.getLogger(__name__)
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Download, DownloadedVideo, DownloadStatus, Settings
from app.schemas import (
    DownloadCreate,
    DownloadBatchCreate,
    DownloadResponse,
    ExtractRequest,
    ExtractResponse,
    PlaylistRequest,
    PlaylistResponse,
    FileInfo,
)
from app.services.downloader import downloader_service
from app.routers.websocket import manager

router = APIRouter(prefix="/api", tags=["downloads"])

# Track active download tasks
active_tasks: dict[int, asyncio.Task] = {}


async def process_download(download_id: int, url: str, options: dict):
    """Background task to process a download."""
    from app.database import async_session
    from app.schemas import DownloadOptions

    logger.info(f"[Download {download_id}] Starting process for URL: {url}")

    async with async_session() as db:
        # Get download record
        result = await db.execute(select(Download).where(Download.id == download_id))
        download = result.scalar_one_or_none()
        if not download:
            logger.error(f"[Download {download_id}] Download record not found in database")
            return

        # Update status to fetching info
        download.status = DownloadStatus.FETCHING_INFO
        await db.commit()
        await manager.broadcast(
            {"type": "status", "id": download_id, "status": "fetching_info"}
        )

        try:
            # Extract info first to get video_id and title
            logger.info(f"[Download {download_id}] Extracting video info...")
            info = await downloader_service.extract_info(url)
            download.video_id = info.get("id")
            download.title = info.get("title", "Unknown")
            download.thumbnail = info.get("thumbnail")
            download.status = DownloadStatus.DOWNLOADING
            await db.commit()
            logger.info(f"[Download {download_id}] Video info extracted: {download.title}")

            await manager.broadcast(
                {
                    "type": "info",
                    "id": download_id,
                    "video_id": download.video_id,
                    "title": download.title,
                    "thumbnail": download.thumbnail,
                    "status": "downloading",
                }
            )

            # Get event loop reference for thread-safe callback
            loop = asyncio.get_running_loop()
            last_broadcast = {"progress": -1, "time": 0}

            # Progress callback - just broadcast, skip DB updates for performance
            async def progress_callback(data: dict):
                try:
                    progress = data.get("progress", 0)
                    logger.debug(f"[Download {download_id}] Broadcasting progress: {progress:.1f}%")
                    await manager.broadcast(
                        {
                            "type": "progress",
                            "id": download_id,
                            "progress": progress,
                            "speed": data.get("speed"),
                            "eta": data.get("eta"),
                        }
                    )
                except Exception as e:
                    logger.error(f"[Download {download_id}] Broadcast error: {e}")

            # Sync wrapper for progress callback (called from executor thread)
            def sync_progress_callback(data: dict):
                current_time = time.time()
                progress = data.get("progress", 0)

                # Throttle: update at most every 0.5 seconds OR if progress jumped significantly
                time_diff = current_time - last_broadcast["time"]
                progress_diff = progress - last_broadcast["progress"]

                should_broadcast = time_diff >= 0.5 or progress_diff >= 2 or data.get("status") == "finished"

                if should_broadcast:
                    last_broadcast["progress"] = progress
                    last_broadcast["time"] = current_time
                    logger.info(f"[Download {download_id}] Progress: {progress:.1f}% | Speed: {data.get('speed')} | ETA: {data.get('eta')}")
                    asyncio.run_coroutine_threadsafe(progress_callback(data), loop)

            # Download
            logger.info(f"[Download {download_id}] Starting download with options: {options}")
            opts = DownloadOptions(**options)
            result = await downloader_service.download(
                url, opts, sync_progress_callback, download_id
            )
            logger.info(f"[Download {download_id}] Download result: {result}")

            if result.get("success"):
                download.status = DownloadStatus.COMPLETED
                download.progress = 100
                download.output_path = result.get("filename")
                download.completed_at = datetime.utcnow()
                await db.commit()

                # Add to downloaded videos history
                video_id = result.get("video_id") or download.video_id
                if video_id:
                    existing = await db.execute(
                        select(DownloadedVideo).where(
                            DownloadedVideo.video_id == video_id
                        )
                    )
                    if not existing.scalar_one_or_none():
                        downloaded_video = DownloadedVideo(
                            video_id=video_id,
                            title=result.get("title") or download.title,
                            channel=result.get("channel"),
                            file_path=result.get("filename"),
                        )
                        db.add(downloaded_video)
                        await db.commit()

                await manager.broadcast(
                    {
                        "type": "completed",
                        "id": download_id,
                        "status": "completed",
                        "output_path": download.output_path,
                    }
                )
            elif result.get("cancelled"):
                download.status = DownloadStatus.CANCELLED
                await db.commit()
                await manager.broadcast(
                    {"type": "cancelled", "id": download_id, "status": "cancelled"}
                )
            else:
                download.status = DownloadStatus.FAILED
                download.error_message = result.get("error", "Unknown error")
                logger.error(f"[Download {download_id}] Download failed: {download.error_message}")
                await db.commit()
                await manager.broadcast(
                    {
                        "type": "error",
                        "id": download_id,
                        "status": "failed",
                        "error": download.error_message,
                    }
                )

        except Exception as e:
            import traceback
            logger.error(f"[Download {download_id}] Exception during download: {e}")
            logger.error(traceback.format_exc())
            download.status = DownloadStatus.FAILED
            download.error_message = str(e)
            await db.commit()
            await manager.broadcast(
                {
                    "type": "error",
                    "id": download_id,
                    "status": "failed",
                    "error": str(e),
                }
            )
        finally:
            if download_id in active_tasks:
                del active_tasks[download_id]


@router.post("/downloads", response_model=DownloadResponse)
async def create_download(
    data: DownloadCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new download."""
    download = Download(
        url=data.url,
        options=data.options.model_dump(),
        status=DownloadStatus.QUEUED,
    )
    db.add(download)
    await db.commit()
    await db.refresh(download)

    # Start background download task
    task = asyncio.create_task(
        process_download(download.id, data.url, data.options.model_dump())
    )
    active_tasks[download.id] = task

    return download


@router.post("/downloads/batch", response_model=list[DownloadResponse])
async def create_batch_download(
    data: DownloadBatchCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create multiple downloads from a list of URLs."""
    downloads = []
    for url in data.urls:
        download = Download(
            url=url,
            options=data.options.model_dump(),
            status=DownloadStatus.QUEUED,
        )
        db.add(download)
        downloads.append(download)

    await db.commit()

    for download in downloads:
        await db.refresh(download)
        task = asyncio.create_task(
            process_download(download.id, download.url, data.options.model_dump())
        )
        active_tasks[download.id] = task

    return downloads


@router.get("/downloads")
async def list_downloads(
    status: Optional[DownloadStatus] = None,
    page: int = 1,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """List all downloads with pagination."""
    # Build base query
    base_query = select(Download)
    if status:
        base_query = base_query.where(Download.status == status)

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    offset = (page - 1) * limit
    query = base_query.order_by(Download.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    downloads = result.scalars().all()

    return {
        "downloads": [DownloadResponse.model_validate(d) for d in downloads],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1
    }


@router.get("/downloads/{download_id}", response_model=DownloadResponse)
async def get_download(download_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific download."""
    result = await db.execute(select(Download).where(Download.id == download_id))
    download = result.scalar_one_or_none()
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return download


@router.delete("/downloads/{download_id}")
async def cancel_download(download_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel or delete a download."""
    result = await db.execute(select(Download).where(Download.id == download_id))
    download = result.scalar_one_or_none()
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.status in [DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.FETCHING_INFO]:
        # Cancel active download
        logger.info(f"[Download {download_id}] Cancelling download...")
        downloader_service.cancel_download(download_id)

        # Update status immediately
        download.status = DownloadStatus.CANCELLED
        await db.commit()

        # Broadcast cancellation to UI
        await manager.broadcast(
            {"type": "cancelled", "id": download_id, "status": "cancelled"}
        )

        # Try to cancel the asyncio task (may not stop the thread immediately)
        if download_id in active_tasks:
            try:
                active_tasks[download_id].cancel()
            except Exception as e:
                logger.warning(f"[Download {download_id}] Error cancelling task: {e}")
            finally:
                del active_tasks[download_id]

        return {"status": "cancelled"}
    else:
        # Delete completed/failed download record
        await db.delete(download)
        await db.commit()
        return {"status": "deleted"}


@router.delete("/downloads")
async def clear_downloads(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Clear downloads by status or all downloads."""
    if status:
        # Map status string to enum
        status_map = {
            "completed": DownloadStatus.COMPLETED,
            "cancelled": DownloadStatus.CANCELLED,
            "failed": DownloadStatus.FAILED,
        }
        if status not in status_map:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        result = await db.execute(
            select(Download).where(Download.status == status_map[status])
        )
        downloads = result.scalars().all()
    else:
        # Clear all non-active downloads
        result = await db.execute(
            select(Download).where(
                Download.status.in_([
                    DownloadStatus.COMPLETED,
                    DownloadStatus.CANCELLED,
                    DownloadStatus.FAILED,
                ])
            )
        )
        downloads = result.scalars().all()

    count = len(downloads)
    for download in downloads:
        await db.delete(download)

    await db.commit()

    return {"deleted": count}


@router.post("/downloads/{download_id}/retry", response_model=DownloadResponse)
async def retry_download(download_id: int, db: AsyncSession = Depends(get_db)):
    """Retry a failed or cancelled download."""
    result = await db.execute(select(Download).where(Download.id == download_id))
    download = result.scalar_one_or_none()
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.status not in [DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Can only retry failed or cancelled downloads")

    # Reset download state
    download.status = DownloadStatus.QUEUED
    download.progress = 0
    download.speed = None
    download.eta = None
    download.error_message = None
    download.completed_at = None
    await db.commit()
    await db.refresh(download)

    # Start background download task
    task = asyncio.create_task(
        process_download(download.id, download.url, download.options)
    )
    active_tasks[download.id] = task

    return download


@router.post("/extract", response_model=ExtractResponse)
async def extract_info(data: ExtractRequest):
    """Extract info from a URL to determine if it's a video, playlist, or channel."""
    try:
        info = await downloader_service.extract_info(data.url)

        # Determine type
        if "entries" in info:
            entry_count = len(info.get("entries", []))
            # Could be playlist or channel
            if "channel" in info.get("extractor", "").lower() or info.get("_type") == "channel":
                content_type = "channel"
            else:
                content_type = "playlist"
            return ExtractResponse(
                type=content_type,
                title=info.get("title", "Unknown"),
                count=entry_count,
                uploader=info.get("uploader") or info.get("channel"),
            )
        else:
            return ExtractResponse(
                type="video",
                title=info.get("title", "Unknown"),
                video_id=info.get("id"),
                uploader=info.get("uploader") or info.get("channel"),
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/playlist", response_model=PlaylistResponse)
async def get_playlist(data: PlaylistRequest, db: AsyncSession = Depends(get_db)):
    """Get all entries from a playlist or channel."""
    try:
        # Get already downloaded video IDs
        result = await db.execute(select(DownloadedVideo.video_id))
        downloaded_ids = set(row[0] for row in result.fetchall())

        title, entries = await downloader_service.get_playlist_entries(
            data.url, downloaded_ids
        )

        return PlaylistResponse(
            title=title,
            entries=entries,
            total_count=len(entries),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/files", response_model=list[FileInfo])
async def list_files(db: AsyncSession = Depends(get_db)):
    """List all downloaded files including those in subfolders."""
    # Get all downloads with thumbnails for lookup
    result = await db.execute(
        select(Download.output_path, Download.thumbnail).where(
            Download.output_path.isnot(None),
            Download.thumbnail.isnot(None)
        )
    )
    # Normalize paths for lookup (handle both / and \ separators, full and relative paths)
    thumbnail_map = {}
    downloads_dir_str = str(settings.downloads_dir.resolve()).replace("\\", "/")
    for row in result.fetchall():
        path = row[0]
        thumbnail = row[1]
        # Normalize to forward slashes
        normalized = path.replace("\\", "/")

        # Store with original path
        thumbnail_map[normalized] = thumbnail
        thumbnail_map[path] = thumbnail

        # Also try to extract relative path if it's a full path
        if normalized.startswith(downloads_dir_str):
            rel_path = normalized[len(downloads_dir_str):].lstrip("/")
            thumbnail_map[rel_path] = thumbnail

        # Also try with ./downloads prefix stripped
        if normalized.startswith("./downloads/"):
            rel_path = normalized[12:]  # len("./downloads/") = 12
            thumbnail_map[rel_path] = thumbnail
        elif normalized.startswith("downloads/"):
            rel_path = normalized[10:]  # len("downloads/") = 10
            thumbnail_map[rel_path] = thumbnail

    files = []
    downloads_path = settings.downloads_dir
    if downloads_path.exists():
        # Recursively find all files
        for file_path in downloads_path.rglob("*"):
            if file_path.is_file():
                # Get relative path from downloads directory
                relative_path = file_path.relative_to(downloads_path)
                stat = file_path.stat()
                relative_path_str = str(relative_path)
                # Normalize for lookup
                normalized_path = relative_path_str.replace("\\", "/")

                # Look up thumbnail by matching output_path
                thumbnail = thumbnail_map.get(normalized_path) or thumbnail_map.get(relative_path_str)

                files.append(
                    FileInfo(
                        name=relative_path_str,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime),
                        thumbnail=thumbnail,
                    )
                )
    return sorted(files, key=lambda f: f.modified, reverse=True)


@router.get("/files/{file_path:path}")
async def get_file(file_path: str):
    """Serve a downloaded file."""
    full_path = settings.downloads_dir / file_path
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Ensure file is within downloads directory (security check)
    try:
        full_path.resolve().relative_to(settings.downloads_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    # Use just the filename for the download name
    filename = Path(file_path).name
    return FileResponse(full_path, filename=filename)


# Cookie Management Endpoints

@router.get("/cookies")
async def get_cookie_status():
    """Get current cookie status."""
    has_cookies = downloader_service.has_cookies()
    if has_cookies:
        stat = settings.cookies_path.stat()
        return {
            "has_cookies": True,
            "file_size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    return {"has_cookies": False}


@router.post("/cookies")
async def upload_cookies(file: UploadFile = File(...)):
    """Upload a cookies.txt file."""
    if not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="File must be a .txt file")

    content = await file.read()

    # Basic validation - check if it looks like a Netscape cookie file
    content_str = content.decode("utf-8", errors="ignore")
    if not ("# Netscape HTTP Cookie File" in content_str or "# HTTP Cookie File" in content_str or ".youtube.com" in content_str):
        raise HTTPException(
            status_code=400,
            detail="Invalid cookie file format. Please export cookies in Netscape/Mozilla format.",
        )

    # Save the file
    settings.cookies_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.cookies_path, "wb") as f:
        f.write(content)

    return {"success": True, "message": "Cookies uploaded successfully"}


@router.post("/cookies/verify")
async def verify_cookies():
    """Verify that the uploaded cookies are valid."""
    result = await downloader_service.verify_cookies()
    return result


@router.delete("/cookies")
async def delete_cookies():
    """Delete the cookies file."""
    if settings.cookies_path.exists():
        settings.cookies_path.unlink()
        return {"success": True, "message": "Cookies deleted"}
    return {"success": False, "message": "No cookies file found"}


# Settings Endpoints

@router.get("/settings/download-options")
async def get_download_options(db: AsyncSession = Depends(get_db)):
    """Get saved download options."""
    result = await db.execute(
        select(Settings).where(Settings.key == "download_options")
    )
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return {}


@router.put("/settings/download-options")
async def save_download_options(options: dict, db: AsyncSession = Depends(get_db)):
    """Save download options."""
    result = await db.execute(
        select(Settings).where(Settings.key == "download_options")
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = options
    else:
        setting = Settings(key="download_options", value=options)
        db.add(setting)

    await db.commit()
    return {"success": True}


# yt-dlp Version Management

@router.get("/yt-dlp/version")
async def get_ytdlp_version():
    """Get current yt-dlp version and check for updates."""
    current_version = yt_dlp.version.__version__

    # Check PyPI for latest version
    latest_version = None
    update_available = False

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://pypi.org/pypi/yt-dlp/json",
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                latest_version = data["info"]["version"]
                update_available = latest_version != current_version
    except Exception as e:
        logger.warning(f"Failed to check for yt-dlp updates: {e}")

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "running_in_docker": settings.running_in_docker
    }


# Database Maintenance Endpoints

@router.get("/maintenance/stats")
async def get_database_stats(db: AsyncSession = Depends(get_db)):
    """Get database statistics."""
    # Count downloads by status
    downloads_result = await db.execute(
        select(Download.status, func.count(Download.id)).group_by(Download.status)
    )
    downloads_by_status = {str(status): count for status, count in downloads_result.fetchall()}

    # Total downloads
    total_downloads = sum(downloads_by_status.values())

    # Count downloaded videos (history)
    history_result = await db.execute(select(func.count(DownloadedVideo.id)))
    total_history = history_result.scalar()

    return {
        "downloads": {
            "total": total_downloads,
            "by_status": downloads_by_status
        },
        "download_history": {
            "total": total_history
        }
    }


@router.delete("/maintenance/downloads")
async def cleanup_old_downloads(
    days: int = 30,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Delete old download records."""
    from datetime import timedelta

    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Build query for non-active downloads older than cutoff
    query = select(Download).where(
        Download.created_at < cutoff_date,
        Download.status.in_([
            DownloadStatus.COMPLETED,
            DownloadStatus.CANCELLED,
            DownloadStatus.FAILED,
        ])
    )

    if status:
        status_map = {
            "completed": DownloadStatus.COMPLETED,
            "cancelled": DownloadStatus.CANCELLED,
            "failed": DownloadStatus.FAILED,
        }
        if status in status_map:
            query = select(Download).where(
                Download.created_at < cutoff_date,
                Download.status == status_map[status]
            )

    result = await db.execute(query)
    downloads = result.scalars().all()

    count = len(downloads)
    for download in downloads:
        await db.delete(download)

    await db.commit()

    return {"deleted": count, "older_than_days": days}


@router.delete("/maintenance/history")
async def clear_download_history(
    days: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """Clear downloaded videos history. If days is specified, only clears entries older than that."""
    from datetime import timedelta

    if days:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        result = await db.execute(
            select(DownloadedVideo).where(DownloadedVideo.downloaded_at < cutoff_date)
        )
    else:
        result = await db.execute(select(DownloadedVideo))

    videos = result.scalars().all()
    count = len(videos)

    for video in videos:
        await db.delete(video)

    await db.commit()

    return {"deleted": count}


@router.get("/maintenance/history/channels")
async def get_history_channels(db: AsyncSession = Depends(get_db)):
    """Get list of channels in download history with video counts."""
    result = await db.execute(
        select(
            DownloadedVideo.channel,
            func.count(DownloadedVideo.id).label('count')
        )
        .group_by(DownloadedVideo.channel)
        .order_by(func.count(DownloadedVideo.id).desc())
    )

    channels = []
    for row in result.fetchall():
        channel_name = row[0] or "Unknown"
        channels.append({
            "channel": channel_name,
            "count": row[1]
        })

    return channels


@router.delete("/maintenance/history/channel/{channel_name:path}")
async def delete_channel_history(
    channel_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Delete download history for a specific channel."""
    if channel_name == "Unknown":
        result = await db.execute(
            select(DownloadedVideo).where(DownloadedVideo.channel.is_(None))
        )
    else:
        result = await db.execute(
            select(DownloadedVideo).where(DownloadedVideo.channel == channel_name)
        )

    videos = result.scalars().all()
    count = len(videos)

    for video in videos:
        await db.delete(video)

    await db.commit()

    return {"deleted": count, "channel": channel_name}


@router.post("/yt-dlp/update")
async def update_ytdlp(restart: bool = False):
    """Update yt-dlp to the latest version."""
    try:
        # Run pip install --upgrade yt-dlp
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True,
                text=True
            )
        )

        if result.returncode == 0:
            message = "yt-dlp updated successfully."
            if restart:
                message += " Server will restart in 2 seconds..."
                # Schedule restart after response is sent
                asyncio.get_event_loop().call_later(2, lambda: os._exit(0))
            else:
                message += " Restart the server to use the new version."

            return {
                "success": True,
                "message": message,
                "output": result.stdout,
                "restarting": restart
            }
        else:
            return {
                "success": False,
                "message": "Update failed",
                "error": result.stderr
            }
    except Exception as e:
        logger.error(f"Failed to update yt-dlp: {e}")
        raise HTTPException(status_code=500, detail=str(e))
