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
    # Initialize database on startup
    await init_db()
    # Start subscription checker
    subscriptions.start_subscription_checker()
    yield


app = FastAPI(
    title="yt-dlp Web",
    description="Web interface for yt-dlp",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Templates
templates_path = Path(__file__).parent.parent / "templates"
templates_path.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=templates_path)

# Include routers
app.include_router(downloads.router)
app.include_router(websocket.router)
app.include_router(subscriptions.router)


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
