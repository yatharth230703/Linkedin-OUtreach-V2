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
#
# IMPORTANT: every alternative in this regex needs to be the FULL variable name
# (or end in `_*` via an explicit char class). Patterns like `PROXY_|` will NOT
# match `PROXY_HOST=` — the `=` in the regex anchors immediately after the
# alternative, so `PROXY_|` only matches a var literally named `PROXY_`.
ENV_FILE="/app/.env.cron"
echo "# Auto-generated env for cron jobs" > "$ENV_FILE"
echo "export STATE_DIR=$STATE_DIR" >> "$ENV_FILE"
env | grep -E '^(ATTIO_API|ATTIO_API_ALT|GEMINI_API_KEY|APIFY_API|PROXY_HOST|PROXY_PORT|PROXY_USERNAME|PROXY_PASSWORD_BASE|PROXY_PASSWORD|USE_PROXY|CLOUD_MODE|DISPLAY|SLACK_WEBHOOK_URL|SLACK_WEBHOOK_URL_ALT|YATH_LINKEDIN_EMAIL|YATH_LINKEDIN_PASSWORD|MAURICE_LINKEDIN_EMAIL|MAURICE_LINKEDIN_PASSWORD|LEON_LINKEDIN_EMAIL|LEON_LINKEDIN_PASSWORD)=' | while read -r line; do
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
