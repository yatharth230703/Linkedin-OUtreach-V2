#!/bin/bash
# Docker entrypoint: ensure state dirs, write env for cron, start xvfb, cron, Flask API.

set -e

# State directory (host-mounted in production via -v $MOUNT_POINT/state:/app/state)
STATE_DIR="${STATE_DIR:-/app/state}"
export STATE_DIR

# Create state subdirectories so the first deploy on a fresh disk doesn't fail.
mkdir -p \
    "$STATE_DIR/cookies" \
    "$STATE_DIR/config" \
    "$STATE_DIR/flags" \
    "$STATE_DIR/status" \
    "$STATE_DIR/logs" \
    "$STATE_DIR/templates"

# Write environment variables to file so cron jobs can source them.
ENV_FILE="/app/.env.cron"
echo "# Auto-generated env for cron jobs" > "$ENV_FILE"
echo "export STATE_DIR=$STATE_DIR" >> "$ENV_FILE"
env | grep -E '^(ATTIO_API|ATTIO_API_ALT|GEMINI_API|APIFY_API|PROXY_|USE_PROXY|CLOUD_MODE|DISPLAY|SLACK_WEBHOOK_URL|SLACK_WEBHOOK_URL_ALT)=' | while read line; do
    echo "export $line" >> "$ENV_FILE"
done

# Start virtual display for headful Chromium.
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
echo "export DISPLAY=:99" >> "$ENV_FILE"

# Start cron daemon.
cron

echo "Starting LinkedIn Bot Backend API on port 8080 (STATE_DIR=$STATE_DIR)..."
python3 /app/backend/server.py
