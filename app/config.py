from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Corvid Cache"
    database_url: str = "sqlite+aiosqlite:///./data/ytdl.db"
    downloads_dir: Path = Path("./downloads")
    cookies_path: Path = Path("./data/cookies.txt")
    max_concurrent_downloads: int = 3
    running_in_docker: bool = False

    class Config:
        env_prefix = "YTDL_"


settings = Settings()

# Ensure directories exist
settings.downloads_dir.mkdir(parents=True, exist_ok=True)
Path("./data").mkdir(parents=True, exist_ok=True)
