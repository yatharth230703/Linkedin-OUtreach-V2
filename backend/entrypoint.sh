#!/bin/bash
# Docker entrypoint: write env for cron, start xvfb, cron, and Flask API

# Write environment variables to file so cron jobs can source them
ENV_FILE="/app/.env.cron"
echo "# Auto-generated env for cron jobs" > "$ENV_FILE"
env | grep -E '^(ATTIO_API|GEMINI_API|APIFY_API|PROXY_|USE_PROXY|CLOUD_MODE|DISPLAY)=' | while read line; do
    echo "export $line" >> "$ENV_FILE"
done

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
echo "export DISPLAY=:99" >> "$ENV_FILE"

# Start cron daemon
cron

echo "Starting LinkedIn Bot Backend API on port 8080..."
python3 /app/backend/server.py
