#!/bin/bash
# Daily bot run script - fallback for single-account operation
# Only runs if bot_enabled flag exists

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$SCRIPT_DIR/bot_enabled" ]; then
    echo "$(date): Bot not enabled, skipping." >> "$SCRIPT_DIR/run_log.txt"
    exit 0
fi

# Source environment variables for cron
if [ -f /app/.env.cron ]; then
    source /app/.env.cron
fi

export DISPLAY=:99

echo "$(date): Starting daily bot run..." >> "$SCRIPT_DIR/run_log.txt"

# Read account_name from config
ACCOUNT_NAME=""
if [ -f "$SCRIPT_DIR/config.json" ]; then
    ACCOUNT_NAME=$(python3 -c "import json; print(json.load(open('$SCRIPT_DIR/config.json')).get('account_name', ''))" 2>/dev/null)
fi

if [ -z "$ACCOUNT_NAME" ]; then
    echo "$(date): No account_name in config. Skipping." >> "$SCRIPT_DIR/run_log.txt"
    exit 1
fi

# Run orchestrator in cloud mode
cd "$APP_DIR"
timeout 21600 python3 -u "$APP_DIR/orchestrator.py" --cloud --account_name "$ACCOUNT_NAME" >> "$SCRIPT_DIR/run_log.txt" 2>&1
EXIT_CODE=$?

echo "$(date): Bot run completed with exit code $EXIT_CODE" >> "$SCRIPT_DIR/run_log.txt"
