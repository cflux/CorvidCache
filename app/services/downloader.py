"""
yt-dlp download service.

This module provides a wrapper around yt-dlp for downloading videos with:
- Async download execution using subprocess for reliable cancellation
- Real-time progress tracking via callbacks
- Cookie-based YouTube authentication
- Support for playlists, channels, and individual videos
- Automatic cleanup of partial downloads on cancellation
"""

import asyncio
import json
import logging
import os
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import re
import sys
import threading

import yt_dlp

from app.config import settings
from app.schemas import DownloadOptions, PlaylistEntry

logger = logging.getLogger(__name__)


class DownloaderService:
    """
    Service for managing video downloads using yt-dlp.

    Uses subprocess execution for downloads to enable reliable cancellation
    on Windows. Tracks active downloads and provides progress callbacks.

    Attributes:
        active_downloads: Map of download ID to asyncio Task.
        _cancel_flags: Map of download ID to cancellation flag.
        _active_processes: Map of download ID to subprocess.Popen instance.
        _current_files: Map of download ID to current file path being downloaded.
    """

    def __init__(self):
        self.active_downloads: dict[int, asyncio.Task] = {}
        self._cancel_flags: dict[int, bool] = {}
        self._active_processes: dict[int, subprocess.Popen] = {}
        self._current_files: dict[int, str] = {}

    def _get_base_opts(self) -> dict:
        """Get base options including cookies if available."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,  # We handle progress ourselves
            "ignoreerrors": False,
        }
        if settings.cookies_path.exists():
            opts["cookiefile"] = str(settings.cookies_path)
        return opts

    def has_cookies(self) -> bool:
        """Check if cookies file exists."""
        return settings.cookies_path.exists()

    async def verify_cookies(self) -> dict:
        """Verify that cookies are valid by checking YouTube account info."""
        if not self.has_cookies():
            return {
                "valid": False,
                "error": "No cookies file found",
                "has_cookies": False,
            }

        opts = self._get_base_opts()
        opts["extract_flat"] = True
        opts["playlist_items"] = "1"  # Only get first item to speed up

        def _verify():
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Try to access the user's "Watch Later" playlist - requires authentication
                    # This is faster than subscriptions feed
                    info = ydl.extract_info(
                        "https://www.youtube.com/playlist?list=WL",
                        download=False,
                    )
                    # If we get here without error, cookies are valid
                    return {
                        "valid": True,
                        "has_cookies": True,
                    }
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                # Check for common auth failure messages
                if any(msg in error_msg.lower() for msg in ["sign in", "login", "private", "cookies"]):
                    return {
                        "valid": False,
                        "error": "Cookies expired or invalid - please re-export from browser",
                        "has_cookies": True,
                    }
                # If we get a different error (like empty playlist), cookies might still be valid
                if "empty" in error_msg.lower() or "no video" in error_msg.lower():
                    return {
                        "valid": True,
                        "has_cookies": True,
                    }
                return {
                    "valid": False,
                    "error": error_msg,
                    "has_cookies": True,
                }
            except Exception as e:
                return {
                    "valid": False,
                    "error": str(e),
                    "has_cookies": True,
                }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _verify)

    def _get_ydl_opts(
        self,
        options: DownloadOptions,
        progress_callback: Optional[Callable] = None,
        download_id: Optional[int] = None,
    ) -> dict:
        output_path = settings.downloads_dir / options.output_template

        opts = self._get_base_opts()
        opts.update({
            "format": options.format,
            "outtmpl": str(output_path),
            "extract_flat": False,
            "nopart": True,  # Avoid .part file renaming issues on Windows
            "retries": 10,   # More retries for flaky connections
        })

        opts["postprocessors"] = []

        # Handle output format conversion
        audio_formats = ["mp3", "m4a", "opus", "flac", "wav", "aac"]
        video_formats = ["mp4", "mkv", "webm", "avi", "mov"]
        output_format = options.output_format.lower()

        if output_format in audio_formats:
            # Audio extraction/conversion
            opts["postprocessors"].append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": output_format,
                "preferredquality": "0",  # Best quality
            })
        elif output_format in video_formats and output_format != "original":
            # Video format conversion
            opts["postprocessors"].append({
                "key": "FFmpegVideoConvertor",
                "preferedformat": output_format,
            })

        if options.embed_metadata:
            opts["postprocessors"].append({"key": "FFmpegMetadata"})

        if options.embed_thumbnail:
            opts["writethumbnail"] = True
            opts["postprocessors"].append({"key": "EmbedThumbnail"})

        if options.subtitles:
            opts["writesubtitles"] = True
            opts["subtitleslangs"] = options.subtitle_langs

        if progress_callback:
            opts["progress_hooks"] = [
                lambda d: self._progress_hook(d, progress_callback, download_id)
            ]
            opts["postprocessor_hooks"] = [
                lambda d: self._postprocessor_hook(d, progress_callback, download_id)
            ]

        return opts

    def _progress_hook(
        self, d: dict, callback: Callable, download_id: Optional[int]
    ) -> None:
        try:
            # Check cancel flag first - raise exception to stop download
            if download_id and self._cancel_flags.get(download_id):
                logger.info(f"Download {download_id} cancelled via progress hook")
                raise yt_dlp.utils.DownloadCancelled("Download cancelled by user")

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                progress = (downloaded / total * 100) if total > 0 else 0

                speed = d.get("speed")
                if speed:
                    if speed > 1024 * 1024:
                        speed_str = f"{speed / 1024 / 1024:.1f} MB/s"
                    elif speed > 1024:
                        speed_str = f"{speed / 1024:.1f} KB/s"
                    else:
                        speed_str = f"{speed:.0f} B/s"
                else:
                    speed_str = None

                eta = d.get("eta")
                if eta:
                    eta = int(eta)
                    mins, secs = divmod(eta, 60)
                    hours, mins = divmod(mins, 60)
                    if hours > 0:
                        eta_str = f"{hours}:{mins:02d}:{secs:02d}"
                    else:
                        eta_str = f"{mins}:{secs:02d}"
                else:
                    eta_str = None

                callback(
                    {
                        "status": "downloading",
                        "progress": progress,
                        "speed": speed_str,
                        "eta": eta_str,
                        "filename": d.get("filename"),
                    }
                )
            elif d["status"] == "finished":
                callback(
                    {
                        "status": "finished",
                        "progress": 100,
                        "filename": d.get("filename"),
                    }
                )
        except yt_dlp.utils.DownloadCancelled:
            raise  # Re-raise cancellation
        except Exception as e:
            logger.error(f"Error in progress hook: {e}")

    def _postprocessor_hook(
        self, d: dict, callback: Callable, download_id: Optional[int]
    ) -> None:
        """
        Handle yt-dlp postprocessor events.

        Called during post-processing phases like merging audio/video,
        embedding thumbnails, converting formats, etc.

        Args:
            d: Dictionary with status info from yt-dlp postprocessor.
            callback: Function to call with progress updates.
            download_id: Optional download ID for tracking.
        """
        try:
            # Debug: log the raw postprocessor hook data
            logger.info(f"[Postprocessor Hook] Download {download_id}: {d}")

            # Check cancel flag
            if download_id and self._cancel_flags.get(download_id):
                logger.info(f"Download {download_id} cancelled via postprocessor hook")
                raise yt_dlp.utils.DownloadCancelled("Download cancelled by user")

            status = d.get("status")
            postprocessor = d.get("postprocessor", "")

            if status in ("started", "processing"):
                # Map postprocessor names to user-friendly descriptions
                pp_names = {
                    "Merger": "Merging video and audio",
                    "FFmpegVideoConvertor": "Converting video format",
                    "FFmpegExtractAudio": "Extracting audio",
                    "FFmpegMetadata": "Embedding metadata",
                    "EmbedThumbnail": "Embedding thumbnail",
                    "FFmpegEmbedSubtitle": "Embedding subtitles",
                }
                description = pp_names.get(postprocessor, f"Processing ({postprocessor})")

                callback(
                    {
                        "status": "processing",
                        "progress": 100,
                        "processing_step": description,
                    }
                )
        except yt_dlp.utils.DownloadCancelled:
            raise
        except Exception as e:
            logger.error(f"Error in postprocessor hook: {e}")

    async def extract_info(self, url: str, download_id: Optional[int] = None, timeout: int = 120) -> dict:
        """
        Extract info from URL without downloading.

        Args:
            url: The URL to extract info from.
            download_id: Optional download ID for cancellation checking.
            timeout: Timeout in seconds (default 120).

        Returns:
            Dictionary containing video/playlist metadata.

        Raises:
            asyncio.TimeoutError: If extraction takes longer than timeout.
            Exception: If extraction fails or is cancelled.
        """
        opts = self._get_base_opts()
        opts["extract_flat"] = "in_playlist"

        def _extract():
            # Check for cancellation before starting
            if download_id and self._cancel_flags.get(download_id):
                raise Exception("Download cancelled")

            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _extract),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Extract info timed out after {timeout}s for URL: {url}")
            raise Exception(f"Info extraction timed out after {timeout} seconds")

    async def get_playlist_entries(
        self, url: str, downloaded_video_ids: set[str]
    ) -> tuple[str, list[PlaylistEntry]]:
        """Get all entries from a playlist/channel."""
        opts = self._get_base_opts()
        opts.update({
            "extract_flat": True,
            "ignoreerrors": True,
        })

        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract)

        entries = []
        for entry in info.get("entries", []):
            if entry is None:
                continue
            video_id = entry.get("id", "")
            duration = entry.get("duration")
            duration_string = None
            if duration:
                mins, secs = divmod(int(duration), 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    duration_string = f"{hours}:{mins:02d}:{secs:02d}"
                else:
                    duration_string = f"{mins}:{secs:02d}"

            # Construct YouTube thumbnail URL if not provided
            thumbnail = entry.get("thumbnail")
            if not thumbnail and video_id:
                thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

            # Check for members-only status
            availability = entry.get("availability", "")
            members_only = availability in ("subscriber_only", "needs_premium")

            # Also check title for common members-only indicators as fallback
            title = entry.get("title", "Unknown")
            if not members_only and title:
                title_lower = title.lower()
                if "(members only)" in title_lower or "[members only]" in title_lower:
                    members_only = True

            entries.append(
                PlaylistEntry(
                    video_id=video_id,
                    title=title,
                    duration=duration,
                    duration_string=duration_string,
                    thumbnail=thumbnail,
                    uploader=entry.get("uploader"),
                    already_downloaded=video_id in downloaded_video_ids,
                    members_only=members_only,
                )
            )

        return info.get("title", "Playlist"), entries

    async def download(
        self,
        url: str,
        options: DownloadOptions,
        progress_callback: Optional[Callable] = None,
        download_id: Optional[int] = None,
    ) -> dict:
        """Download a video using subprocess for reliable cancellation."""
        logger.info(f"Starting download {download_id}: {url}")
        self._cancel_flags[download_id] = False

        # Build yt-dlp command
        output_path = settings.downloads_dir / options.output_template
        cmd = [
            sys.executable, "-u", "-m", "yt_dlp",  # -u for unbuffered Python output
            "--newline",  # Progress on new lines for parsing
            "--no-colors",
            "--progress",  # Force progress output
            "-f", options.format,
            "-o", str(output_path),
            "--no-part",  # Avoid rename issues on Windows
            "--retries", "10",
            "--print", "after_move:filepath",  # Print final filepath
        ]

        # Add cookies if available
        if settings.cookies_path.exists():
            cmd.extend(["--cookies", str(settings.cookies_path)])

        # Add postprocessors
        audio_formats = ["mp3", "m4a", "opus", "flac", "wav", "aac"]
        video_formats = ["mp4", "mkv", "webm", "avi", "mov"]
        output_format = options.output_format.lower()

        if output_format in audio_formats:
            cmd.extend(["-x", "--audio-format", output_format, "--audio-quality", "0"])
        elif output_format in video_formats and output_format != "original":
            cmd.extend(["--remux-video", output_format])

        if options.embed_metadata:
            cmd.append("--embed-metadata")

        if options.embed_thumbnail:
            cmd.append("--embed-thumbnail")

        if options.subtitles:
            cmd.extend(["--write-subs", "--sub-langs", ",".join(options.subtitle_langs)])

        # Add URL last
        cmd.append(url)

        logger.info(f"[Download {download_id}] Running command: {' '.join(cmd)}")

        loop = asyncio.get_running_loop()
        current_file = {"path": None}  # Track current file for cleanup

        def _run_process():
            import time as time_module

            # Set environment to disable Python buffering in subprocess
            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            self._active_processes[download_id] = process

            filename = None
            last_progress_time = 0
            last_progress_value = 0  # Track last progress to detect new streams
            sent_processing_status = False  # Track if we've sent processing status

            try:
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    # Check for cancellation
                    if self._cancel_flags.get(download_id):
                        logger.info(f"[Download {download_id}] Cancellation detected, terminating process")
                        self._terminate_process(process)
                        return {"cancelled": True, "partial_file": current_file["path"]}

                    # Log all lines for debugging
                    logger.info(f"[Download {download_id}] yt-dlp: {line}")

                    # Parse destination file
                    if "[download] Destination:" in line:
                        current_file["path"] = line.split("Destination:", 1)[1].strip()
                        self._current_files[download_id] = current_file["path"]
                        logger.info(f"[Download {download_id}] Set destination: {current_file['path']}")

                    # Parse progress line: "[download]  45.2% of 100.00MiB at 5.23MiB/s ETA 00:30"
                    elif "[download]" in line and "%" in line:
                        try:
                            # Extract percentage
                            match = re.search(r'(\d+\.?\d*)%', line)
                            if match:
                                progress = float(match.group(1))

                                # Extract speed (handles both "at X" and "~X" formats)
                                speed_match = re.search(r'(?:at|~)\s*([\d.]+\s*\w+/s)', line)
                                speed = speed_match.group(1) if speed_match else None

                                # Extract ETA
                                eta_match = re.search(r'ETA\s+(\d+:\d+(?::\d+)?)', line)
                                eta = eta_match.group(1) if eta_match else None

                                # Detect if a new stream started (progress dropped significantly)
                                # This happens with bestvideo+bestaudio downloads
                                if progress < 50 and last_progress_value > 90:
                                    logger.info(f"[Download {download_id}] New stream detected (progress dropped from {last_progress_value:.1f}% to {progress:.1f}%)")
                                    sent_processing_status = False  # Reset so we can trigger after this stream

                                last_progress_value = progress

                                # Throttle callbacks
                                current_time = time_module.time()
                                should_update = current_time - last_progress_time >= 0.5 or progress >= 99
                                if progress_callback and should_update:
                                    last_progress_time = current_time
                                    logger.info(f"[Download {download_id}] Progress: {progress:.1f}% Speed: {speed} ETA: {eta}")
                                    try:
                                        # When download hits 100%, switch to processing status
                                        # Only if we haven't already (handles multi-stream downloads)
                                        if progress >= 99.9 and not sent_processing_status:
                                            sent_processing_status = True
                                            logger.info(f"[Download {download_id}] Stream complete, checking for post-processing...")
                                            progress_callback({
                                                "status": "processing",
                                                "progress": 100,
                                                "processing_step": "Processing...",
                                            })
                                        elif not sent_processing_status:
                                            # Only send progress if we haven't switched to processing
                                            progress_callback({
                                                "progress": progress,
                                                "speed": speed,
                                                "eta": eta,
                                            })
                                    except Exception as cb_error:
                                        logger.error(f"[Download {download_id}] Callback error: {cb_error}")
                        except (ValueError, IndexError) as e:
                            logger.debug(f"[Download {download_id}] Progress parse error: {e}")

                    # Detect post-processing steps (update description if we see specific messages)
                    elif line.startswith("[") and progress_callback:
                        # Map yt-dlp postprocessor names to user-friendly descriptions
                        pp_patterns = {
                            "[Merger]": "Merging video and audio",
                            "[FFmpegVideoConvertor]": "Converting video format",
                            "[ExtractAudio]": "Extracting audio",
                            "[FFmpegMetadata]": "Embedding metadata",
                            "[EmbedThumbnail]": "Embedding thumbnail",
                            "[FFmpegEmbedSubtitle]": "Embedding subtitles",
                            "[FFmpegVideoRemuxer]": "Remuxing video",
                            "[MoveFiles]": "Moving files",
                            "[ModifyChapters]": "Processing chapters",
                            "[SponsorBlock]": "Processing sponsor segments",
                        }

                        for pattern, description in pp_patterns.items():
                            if line.startswith(pattern):
                                sent_processing_status = True  # Mark as sent
                                logger.info(f"[Download {download_id}] Postprocessing: {description}")
                                try:
                                    progress_callback({
                                        "status": "processing",
                                        "progress": 100,
                                        "processing_step": description,
                                    })
                                except Exception as cb_error:
                                    logger.error(f"[Download {download_id}] Processing callback error: {cb_error}")
                                break

                    # Capture final filepath from --print
                    if line and not line.startswith("[") and Path(line).suffix:
                        # This might be the final filepath from --print
                        if Path(line).exists() or "%" not in line:
                            filename = line

                process.wait()

                if self._cancel_flags.get(download_id):
                    return {"cancelled": True, "partial_file": current_file["path"]}

                if process.returncode == 0:
                    return {"success": True, "filename": filename or current_file["path"]}
                else:
                    return {"success": False, "error": f"yt-dlp exited with code {process.returncode}"}

            except Exception as e:
                logger.error(f"[Download {download_id}] Process error: {e}")
                return {"success": False, "error": str(e)}
            finally:
                if download_id in self._active_processes:
                    del self._active_processes[download_id]

        try:
            result = await loop.run_in_executor(None, _run_process)

            if result.get("cancelled"):
                logger.info(f"[Download {download_id}] Download was cancelled")
                # Clean up partial file
                partial_file = result.get("partial_file")
                if partial_file:
                    self._cleanup_partial_file(partial_file)
                return {"success": False, "error": "Download cancelled", "cancelled": True}
            elif result.get("success"):
                logger.info(f"[Download {download_id}] Download completed successfully")
                return {
                    "success": True,
                    "filename": result.get("filename"),
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}

        except asyncio.CancelledError:
            logger.info(f"[Download {download_id}] Task was cancelled")
            if download_id in self._active_processes:
                self._terminate_process(self._active_processes[download_id])
            # Clean up partial file
            if current_file["path"]:
                self._cleanup_partial_file(current_file["path"])
            return {"success": False, "error": "Download cancelled", "cancelled": True}
        except Exception as e:
            logger.error(f"[Download {download_id}] Error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if download_id in self._cancel_flags:
                del self._cancel_flags[download_id]
            if download_id in self._active_processes:
                del self._active_processes[download_id]
            if download_id in self._current_files:
                del self._current_files[download_id]

    def _cleanup_partial_file(self, filepath: str):
        """Clean up a partially downloaded file and all related files."""
        if not filepath:
            return

        try:
            path = Path(filepath)
            logger.info(f"Attempting to clean up: {filepath}")

            # Wait a moment for the process to fully release the file
            import time
            time.sleep(0.5)

            # Get the base name to find all related files
            # e.g., "video.mp4" -> "video"
            base_name = path.stem
            parent_dir = path.parent

            if parent_dir.exists():
                # Delete all files that start with the base name
                self._delete_files_by_basename(parent_dir, base_name)

        except Exception as e:
            logger.error(f"Error cleaning up partial file {filepath}: {e}")

    def _terminate_process(self, process: subprocess.Popen):
        """Terminate a subprocess."""
        try:
            if sys.platform == "win32":
                # On Windows, use taskkill to kill the process tree
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                )
            else:
                import signal
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=5)
        except Exception as e:
            logger.error(f"Error terminating process: {e}")
            try:
                process.kill()
            except:
                pass

    def cancel_download(self, download_id: int) -> None:
        """Request cancellation of a download."""
        logger.info(f"Cancelling download {download_id}")
        self._cancel_flags[download_id] = True

        # Get filepath before killing process
        filepath = self._current_files.get(download_id)

        # Kill the subprocess if running
        if download_id in self._active_processes:
            process = self._active_processes[download_id]
            logger.info(f"[Download {download_id}] Killing subprocess PID {process.pid}")
            self._terminate_process(process)

        # Wait a moment for process to fully terminate and release files
        import time
        time.sleep(1)

        # Clean up partial files
        if filepath:
            logger.info(f"[Download {download_id}] Cleaning up file: {filepath}")
            self._cleanup_partial_file(filepath)
            if download_id in self._current_files:
                del self._current_files[download_id]

        # Also search for any recently created files in downloads directory
        self._cleanup_recent_partial_files()

    def _cleanup_recent_partial_files(self):
        """Clean up any .ytdl files and all related files with the same base name."""
        try:
            downloads_dir = settings.downloads_dir
            if not downloads_dir.exists():
                return

            # Search recursively for .ytdl files (these indicate incomplete downloads)
            for ytdl_file in downloads_dir.rglob("*.ytdl"):
                logger.info(f"Found incomplete download marker: {ytdl_file}")

                # The video file is the .ytdl filename without the .ytdl extension
                # e.g., "video.mp4.ytdl" -> "video.mp4"
                video_file = Path(str(ytdl_file)[:-5])  # Remove ".ytdl"

                # Get the base name without extension to find all related files
                # e.g., "video.mp4" -> "video"
                base_name = video_file.stem
                parent_dir = video_file.parent

                # Delete all files that start with the base name
                self._delete_files_by_basename(parent_dir, base_name)

                # Delete the .ytdl marker file
                try:
                    if ytdl_file.exists():
                        ytdl_file.unlink()
                        logger.info(f"Deleted .ytdl marker: {ytdl_file}")
                except Exception as e:
                    logger.error(f"Failed to delete {ytdl_file}: {e}")

        except Exception as e:
            logger.error(f"Error in _cleanup_recent_partial_files: {e}")

    def _delete_files_by_basename(self, directory: Path, base_name: str):
        """Delete all files in a directory that match the base name."""
        if not directory.exists():
            return

        try:
            # Find all files that start with the base name
            for file_path in directory.glob(f"{base_name}*"):
                if file_path.is_file():
                    logger.info(f"Deleting related file: {file_path}")
                    try:
                        file_path.unlink()
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error deleting files by basename {base_name}: {e}")

    async def get_formats(self, url: str) -> list[dict]:
        """Get available formats for a URL."""
        opts = self._get_base_opts()

        def _get_formats():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("formats", [])

        loop = asyncio.get_event_loop()
        formats = await loop.run_in_executor(None, _get_formats)

        result = []
        for f in formats:
            result.append(
                {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution") or f"{f.get('width', '?')}x{f.get('height', '?')}",
                    "filesize": f.get("filesize"),
                    "format_note": f.get("format_note"),
                }
            )
        return result


downloader_service = DownloaderService()
