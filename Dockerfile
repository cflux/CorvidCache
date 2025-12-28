FROM python:3.11-slim

# Install ffmpeg and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY templates/ ./templates/

# Copy and set up entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories for data and downloads
RUN mkdir -p /app/data /app/downloads

# Set environment variables
ENV YTDL_DATABASE_URL=sqlite+aiosqlite:///./data/ytdl.db
ENV YTDL_DOWNLOADS_DIR=/app/downloads
ENV UMASK=000

# Expose port
EXPOSE 8080

# Use entrypoint to set umask before running the application
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
