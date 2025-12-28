#!/bin/bash

# Handle PUID/PGID for unraid compatibility
PUID=${PUID:-99}
PGID=${PGID:-100}

# If running as root and PUID/PGID are set, switch to that user
if [ "$(id -u)" = "0" ]; then
    # Use existing group with PGID or create appgroup
    if getent group "$PGID" > /dev/null 2>&1; then
        GROUP_NAME=$(getent group "$PGID" | cut -d: -f1)
    else
        groupadd -g "$PGID" appgroup 2>/dev/null || true
        GROUP_NAME="appgroup"
    fi

    # Create user if it doesn't exist
    if ! getent passwd appuser > /dev/null 2>&1; then
        useradd -u "$PUID" -g "$PGID" -m -s /bin/bash appuser 2>/dev/null || true
    else
        # Update existing user's UID/GID
        usermod -u "$PUID" -g "$PGID" appuser 2>/dev/null || true
    fi

    echo "Running as UID=$PUID, GID=$PGID"

    # Fix ownership of app directories BEFORE starting the app
    echo "Fixing permissions on /app/data and /app/downloads..."
    chown -R "$PUID:$PGID" /app/data /app/downloads 2>/dev/null || true
    chmod -R 755 /app/data /app/downloads 2>/dev/null || true

    # Set umask
    if [ -n "$UMASK" ]; then
        umask "$UMASK"
        echo "Set umask to $UMASK"
    fi

    # Execute the main command as appuser
    exec gosu appuser "$@"
else
    # Already running as non-root
    echo "Running as UID=$(id -u), GID=$(id -g)"

    # Set umask
    if [ -n "$UMASK" ]; then
        umask "$UMASK"
        echo "Set umask to $UMASK"
    fi

    exec "$@"
fi
