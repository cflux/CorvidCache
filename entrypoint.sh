#!/bin/bash

# Set umask from environment variable (default 000 for unraid compatibility)
if [ -n "$UMASK" ]; then
    umask "$UMASK"
    echo "Set umask to $UMASK"
fi

# Handle PUID/PGID for unraid compatibility
PUID=${PUID:-99}
PGID=${PGID:-100}

# If running as root and PUID/PGID are set, switch to that user
if [ "$(id -u)" = "0" ]; then
    # Create group if it doesn't exist
    if ! getent group appgroup > /dev/null 2>&1; then
        groupadd -g "$PGID" appgroup || true
    fi

    # Create user if it doesn't exist
    if ! getent passwd appuser > /dev/null 2>&1; then
        useradd -u "$PUID" -g "$PGID" -m -s /bin/bash appuser || true
    fi

    # Ensure the user has correct UID/GID (in case they already existed with different values)
    usermod -u "$PUID" appuser 2>/dev/null || true
    groupmod -g "$PGID" appgroup 2>/dev/null || true

    echo "Running as UID=$PUID, GID=$PGID"

    # Ensure app directories are owned by appuser
    chown -R appuser:appgroup /app/data /app/downloads 2>/dev/null || true

    # Execute the main command as appuser
    exec gosu appuser "$@"
else
    # Already running as non-root, just execute
    echo "Running as UID=$(id -u), GID=$(id -g)"
    exec "$@"
fi
