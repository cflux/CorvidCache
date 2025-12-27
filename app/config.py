"""
Application configuration module.

Uses Pydantic settings management to load configuration from environment
variables with the YTDL_ prefix. Automatically creates required directories
on module load.
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings can be overridden by setting environment variables
    with the YTDL_ prefix (e.g., YTDL_DOWNLOADS_DIR).

    Attributes:
        app_name: Display name for the application.
        database_url: SQLAlchemy async database connection string.
        downloads_dir: Directory where downloaded files are saved.
        cookies_path: Path to the YouTube cookies.txt file for authentication.
        max_concurrent_downloads: Maximum number of simultaneous downloads.
        running_in_docker: Flag indicating if running inside Docker container.
    """
    app_name: str = "Corvid Cache"
    database_url: str = "sqlite+aiosqlite:///./data/ytdl.db"
    downloads_dir: Path = Path("./downloads")
    cookies_path: Path = Path("./data/cookies.txt")
    max_concurrent_downloads: int = 1
    running_in_docker: bool = False

    class Config:
        env_prefix = "YTDL_"


# Global settings instance
settings = Settings()

# Ensure required directories exist on startup
settings.downloads_dir.mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(parents=True, exist_ok=True)
