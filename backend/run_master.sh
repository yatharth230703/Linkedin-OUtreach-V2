#!/bin/bash
# Master cron script - runs hourly, checks each account's time window
# and launches orchestrator for enabled accounts.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
LOG="$SCRIPT_DIR/run_log.txt"

# Source environment variables for cron
if [ -f /app/.env.cron ]; then
    source /app/.env.cron
fi

export DISPLAY=:99

# Account definitions: slug, UTC start hour, UTC end hour
ACCOUNTS=(
    "yatharth_bisht:0:24"
    "maurice:7:15"
    "leon:15:23"
)

CURRENT_HOUR=$(date -u +%H | sed 's/^0//')

echo "$(date -u): Master cron check (UTC hour: $CURRENT_HOUR)" >> "$LOG"

for entry in "${ACCOUNTS[@]}"; do
    IFS=':' read -r SLUG START END <<< "$entry"

    ENABLED_FLAG="$SCRIPT_DIR/bot_enabled_${SLUG}"
    PID_FILE="$SCRIPT_DIR/pid_${SLUG}.txt"

    # Skip if not enabled
    if [ ! -f "$ENABLED_FLAG" ]; then
        continue
    fi

    # Check time window
    if [ "$CURRENT_HOUR" -lt "$START" ] || [ "$CURRENT_HOUR" -ge "$END" ]; then
        echo "$(date -u): $SLUG - outside time window ($START-$END UTC), skipping" >> "$LOG"
        continue
    fi

    # Check if already running
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "$(date -u): $SLUG - already running (PID $PID), skipping" >> "$LOG"
            continue
        else
            echo "$(date -u): $SLUG - stale PID file (PID $PID not running), cleaning up" >> "$LOG"
            rm -f "$PID_FILE"
        fi
    fi

    # Check if ANY other account is currently running (sequential execution)
    OTHER_RUNNING=false
    for other_entry in "${ACCOUNTS[@]}"; do
        IFS=':' read -r OTHER_SLUG _ _ <<< "$other_entry"
        if [ "$OTHER_SLUG" = "$SLUG" ]; then
            continue
        fi
        OTHER_PID_FILE="$SCRIPT_DIR/pid_${OTHER_SLUG}.txt"
        if [ -f "$OTHER_PID_FILE" ]; then
            OTHER_PID=$(cat "$OTHER_PID_FILE")
            if kill -0 "$OTHER_PID" 2>/dev/null; then
                echo "$(date -u): $SLUG - another account ($OTHER_SLUG, PID $OTHER_PID) is running, skipping" >> "$LOG"
                OTHER_RUNNING=true
                break
            fi
        fi
    done

    if [ "$OTHER_RUNNING" = true ]; then
        continue
    fi

    # Reconstruct account_name from slug (replace _ with space, title case)
    ACCOUNT_NAME=$(echo "$SLUG" | sed 's/_/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))}1')

    echo "$(date -u): Launching orchestrator for $ACCOUNT_NAME" >> "$LOG"

    cd "$APP_DIR"
    nohup python3 -u "$APP_DIR/orchestrator.py" --cloud --account_name "$ACCOUNT_NAME" \
        >> "$APP_DIR/daily_log.txt" 2>&1 &
    BOT_PID=$!

    echo "$BOT_PID" > "$PID_FILE"
    echo "$(date -u): $SLUG started with PID $BOT_PID" >> "$LOG"
done
