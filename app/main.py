"""
FastAPI application entry point.

This module creates and configures the FastAPI application, including:
- Database initialization on startup
- Static file serving
- Jinja2 template configuration
- Router registration
- Subscription checker background task
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_db
from app.routers import downloads, websocket, subscriptions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown tasks:
    - Startup: Initialize database tables, download semaphore, start subscription checker
    - Shutdown: Cleanup (handled automatically by context manager)
    """
    await init_db()
    await downloads.init_download_semaphore()
    subscriptions.start_subscription_checker()
    yield


# Create FastAPI application instance
app = FastAPI(
    title="Corvid Cache",
    description="Self-hosted web interface for yt-dlp",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files directory for CSS, JS, and images
static_path = Path(__file__).parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Configure Jinja2 templates
templates_path = Path(__file__).parent.parent / "templates"
templates_path.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=templates_path)

# Register API routers
app.include_router(downloads.router)
app.include_router(websocket.router)
app.include_router(subscriptions.router)


@app.get("/")
async def index(request: Request):
    """
    Serve the main web interface.

    Returns the index.html template which contains the full
    single-page application UI.
    """
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    # Run development server when executed directly
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
