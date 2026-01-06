import asyncio
import fnmatch
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models import Subscription, DownloadedVideo, Download, DownloadStatus
from app.schemas import (
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
    DownloadOptions,
)
from app.services.downloader import downloader_service
from app.routers.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

# Background task reference
subscription_checker_task: Optional[asyncio.Task] = None


async def check_subscription(subscription_id: int):
    """Check a subscription for new videos and queue downloads."""
    async with async_session() as db:
        try:
            # Fetch subscription within this session so updates persist
            result = await db.execute(
                select(Subscription).where(Subscription.id == subscription_id)
            )
            subscription = result.scalar_one_or_none()
            if not subscription:
                print(f"Subscription {subscription_id} not found")
                return 0

            # Get already downloaded video IDs
            result = await db.execute(select(DownloadedVideo.video_id))
            downloaded_ids = set(row[0] for row in result.fetchall())

            # Get playlist entries
            title, entries = await downloader_service.get_playlist_entries(
                subscription.url, downloaded_ids
            )

            # Filter out members-only videos if not included
            if not subscription.include_members:
                entries = [e for e in entries if not e.members_only]

            # Filter by title pattern if set (supports wildcards like * and ?)
            if subscription.title_filter:
                pattern = subscription.title_filter
                original_count = len(entries)
                entries = [e for e in entries if fnmatch.fnmatch(e.title.lower(), pattern.lower())]
                logger.info(f"Title filter '{pattern}' matched {len(entries)}/{original_count} videos for {subscription.name}")

            # Limit to keep_last_n newest videos if set
            if subscription.keep_last_n and subscription.keep_last_n > 0:
                entries = entries[:subscription.keep_last_n]

            # Find new videos (not already downloaded)
            new_videos = [e for e in entries if not e.already_downloaded]

            if new_videos:
                # Queue downloads for new videos
                options = DownloadOptions(**subscription.options)

                for entry in new_videos:
                    video_url = f"https://www.youtube.com/watch?v={entry.video_id}"

                    # Create download record
                    download = Download(
                        url=video_url,
                        video_id=entry.video_id,
                        title=entry.title,
                        options=subscription.options,
                        status=DownloadStatus.QUEUED,
                    )
                    db.add(download)
                    await db.commit()
                    await db.refresh(download)

                    # Broadcast new download
                    await manager.broadcast({
                        "type": "new_download",
                        "id": download.id,
                        "title": download.title,
                        "url": download.url,
                        "subscription": subscription.name,
                    })

                    # Start download in background
                    from app.routers.downloads import process_download
                    asyncio.create_task(
                        process_download(download.id, video_url, subscription.options)
                    )

            # Update subscription last_checked and video count
            subscription.last_checked = datetime.utcnow()
            subscription.last_video_count = len(entries)
            await db.commit()

            return len(new_videos)

        except Exception as e:
            print(f"Error checking subscription {subscription_id}: {e}")
            return 0


async def subscription_checker_loop():
    """Background loop that checks subscriptions periodically."""
    while True:
        try:
            async with async_session() as db:
                # Get all enabled subscriptions
                result = await db.execute(
                    select(Subscription).where(Subscription.enabled == True)
                )
                subscriptions = result.scalars().all()

                for sub in subscriptions:
                    # Check if it's time to check this subscription
                    if sub.last_checked is None:
                        should_check = True
                    else:
                        next_check = sub.last_checked + timedelta(hours=sub.check_interval_hours)
                        should_check = datetime.utcnow() >= next_check

                    if should_check:
                        print(f"Checking subscription: {sub.name}")
                        new_count = await check_subscription(sub.id)
                        if new_count > 0:
                            print(f"Found {new_count} new videos for {sub.name}")

        except Exception as e:
            print(f"Error in subscription checker loop: {e}")

        # Wait 5 minutes before next check cycle
        await asyncio.sleep(300)


def start_subscription_checker():
    """Start the background subscription checker."""
    global subscription_checker_task
    if subscription_checker_task is None or subscription_checker_task.done():
        subscription_checker_task = asyncio.create_task(subscription_checker_loop())


@router.on_event("startup")
async def startup():
    start_subscription_checker()


@router.post("", response_model=SubscriptionResponse)
async def create_subscription(
    data: SubscriptionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new subscription."""
    # Extract info to get the name if not provided
    name = data.name
    if not name:
        try:
            info = await downloader_service.extract_info(data.url)
            name = info.get("title") or info.get("uploader") or "Unknown"
        except Exception:
            name = "Unknown"

    subscription = Subscription(
        url=data.url,
        name=name,
        check_interval_hours=data.check_interval_hours,
        options=data.options.model_dump(),
        keep_last_n=data.keep_last_n,
        include_members=data.include_members,
        title_filter=data.title_filter,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    # Start the checker if not running
    start_subscription_checker()

    return subscription


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(db: AsyncSession = Depends(get_db)):
    """List all subscriptions."""
    result = await db.execute(
        select(Subscription).order_by(Subscription.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(subscription_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific subscription."""
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: int,
    data: SubscriptionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a subscription."""
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if data.name is not None:
        subscription.name = data.name
    if data.check_interval_hours is not None:
        subscription.check_interval_hours = data.check_interval_hours
    if data.enabled is not None:
        subscription.enabled = data.enabled
    if data.options is not None:
        subscription.options = data.options.model_dump()
    if data.keep_last_n is not None:
        # Allow setting to None by passing 0 or negative
        subscription.keep_last_n = data.keep_last_n if data.keep_last_n > 0 else None
    if data.include_members is not None:
        subscription.include_members = data.include_members
    if data.title_filter is not None:
        # Allow clearing by passing empty string
        subscription.title_filter = data.title_filter if data.title_filter else None

    await db.commit()
    await db.refresh(subscription)
    return subscription


@router.delete("/{subscription_id}")
async def delete_subscription(subscription_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a subscription."""
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    await db.delete(subscription)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{subscription_id}/check")
async def check_subscription_now(
    subscription_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a check for new videos."""
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    new_count = await check_subscription(subscription_id)
    return {"new_videos": new_count}
