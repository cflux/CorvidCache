#!/bin/bash

# Set umask from environment variable (default 000 for unraid compatibility)
if [ -n "$UMASK" ]; then
    umask "$UMASK"
    echo "Set umask to $UMASK"
fi

# Execute the main command
exec "$@"
