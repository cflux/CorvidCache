# Corvid Cache

A self-hosted web interface for yt-dlp with real-time progress tracking, playlist management, and download history.

## Features

- **Video Downloads** - Download videos from YouTube and other supported sites
- **Playlist/Channel Support** - Preview and select individual videos from playlists or channels
- **Real-time Progress** - Live download progress via WebSocket
- **Download History** - Track previously downloaded videos to avoid duplicates
- **Smart Selection** - Auto-select only new videos when browsing playlists
- **Members-Only Detection** - Identify and filter members-only content
- **Format Options** - Choose quality, output format, subtitles, and more
- **YouTube Authentication** - Support for cookies to access private/age-restricted content
- **Dark/Light Theme** - Toggle between themes
- **Docker Support** - Easy deployment with Docker Compose

## Installation

### Docker (Recommended)

```bash
git clone https://github.com/cflux/CorvidCache.git
cd CorvidCache
docker-compose up -d
```

Access the web interface at `http://localhost:8080`

### Local Development

```bash
git clone https://github.com/cflux/CorvidCache.git
cd CorvidCache

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Configuration

Environment variables (prefix with `YTDL_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `YTDL_DOWNLOADS_DIR` | `./downloads` | Directory for downloaded files |
| `YTDL_DATABASE_URL` | `sqlite+aiosqlite:///./data/ytdl.db` | Database connection string |
| `YTDL_MAX_CONCURRENT_DOWNLOADS` | `3` | Maximum simultaneous downloads |
| `YTDL_RUNNING_IN_DOCKER` | `false` | Set to `true` when running in Docker |

## Usage

1. **Download a Video** - Paste a URL in the sidebar and click Download
2. **Browse Playlists** - Paste a playlist/channel URL to preview and select videos
3. **Manage Downloads** - View progress, retry failed downloads, or cancel active ones
4. **Browse Files** - Access downloaded files from the Files tab
5. **YouTube Auth** - Upload cookies.txt for private/age-restricted content (click the auth badge in navbar)

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy, yt-dlp
- **Frontend**: Bootstrap 5, vanilla JavaScript
- **Database**: SQLite
- **Real-time**: WebSocket

## License

MIT License - see [LICENSE](LICENSE) for details
