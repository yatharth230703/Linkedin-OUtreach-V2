#!/bin/bash
# Daily bot run script - executed by cron
# Only runs if bot_enabled flag exists

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$SCRIPT_DIR/bot_enabled" ]; then
    echo "$(date): Bot not enabled, skipping." >> "$SCRIPT_DIR/run_log.txt"
    exit 0
fi

export DISPLAY=:99

echo "$(date): Starting daily bot run..." >> "$SCRIPT_DIR/run_log.txt"

# Step 1: Inject cookies from extension
cd "$APP_DIR"
timeout 120 python3 "$SCRIPT_DIR/inject_cookies.py" >> "$SCRIPT_DIR/run_log.txt" 2>&1

if [ $? -ne 0 ]; then
    echo "$(date): Cookie injection failed." >> "$SCRIPT_DIR/run_log.txt"
    exit 1
fi

# Step 2: Run orchestrator in test mode (disables user-presence checks)
timeout 21600 python3 "$APP_DIR/orchestrator.py" --test --template_1 >> "$SCRIPT_DIR/run_log.txt" 2>&1
EXIT_CODE=$?

echo "$(date): Bot run completed with exit code $EXIT_CODE" >> "$SCRIPT_DIR/run_log.txt"
