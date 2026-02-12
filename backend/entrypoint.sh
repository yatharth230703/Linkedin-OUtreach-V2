#!/bin/bash
# Docker entrypoint: start xvfb, cron, and Flask API

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Start cron daemon
cron

echo "Starting LinkedIn Bot Backend API on port 8080..."
python3 /app/backend/server.py
