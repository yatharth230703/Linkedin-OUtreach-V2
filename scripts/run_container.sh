#!/bin/bash
# run_container.sh — single source of truth for how the linkedin-bot container is launched.
#
# Used by:
#   - Terraform metadata_startup_script (first boot of the VM)
#   - scripts/redeploy.sh                (every CI deploy)
#
# Inputs (env vars):
#   IMAGE                  full Docker image ref to run (required)
#   MOUNT_POINT            persistent disk mount path (default /mnt/bot-data)
#
# Reads secrets from Google Secret Manager via the VM's attached service account.
# All env vars are pulled fresh on every run so secret rotations take effect.

set -euo pipefail

: "${IMAGE:?IMAGE env var is required (e.g. asia-south1-docker.pkg.dev/.../bot:latest)}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/bot-data}"
STATE_HOST_DIR="$MOUNT_POINT/state"

# Ensure state directory exists on the persistent disk so the bind mount works.
mkdir -p \
    "$STATE_HOST_DIR/cookies" \
    "$STATE_HOST_DIR/config" \
    "$STATE_HOST_DIR/flags" \
    "$STATE_HOST_DIR/status" \
    "$STATE_HOST_DIR/logs" \
    "$STATE_HOST_DIR/templates"

# Pull secrets from Secret Manager. Best-effort: empty string on failure so the
# container can still start even if a secret is missing (the bot will log it).
fetch_secret() {
    gcloud secrets versions access latest --secret="$1" 2>/dev/null || echo ""
}

ATTIO_API="$(fetch_secret ATTIO_API)"
GEMINI_API_KEY="$(fetch_secret GEMINI_API_KEY)"
APIFY_API="$(fetch_secret APIFY_API)"
YATH_LINKEDIN_EMAIL="$(fetch_secret YATH_LINKEDIN_EMAIL)"
YATH_LINKEDIN_PASSWORD="$(fetch_secret YATH_LINKEDIN_PASSWORD)"
PROXY_HOST="$(fetch_secret PROXY_HOST)"
PROXY_PORT="$(fetch_secret PROXY_PORT)"
PROXY_USERNAME="$(fetch_secret PROXY_USERNAME)"
PROXY_PASSWORD_BASE="$(fetch_secret PROXY_PASSWORD_BASE)"
USE_PROXY="$(fetch_secret USE_PROXY)"
[ -z "$USE_PROXY" ] && USE_PROXY="true"
SLACK_WEBHOOK_URL="$(fetch_secret SLACK_WEBHOOK_URL)"
SLACK_WEBHOOK_URL_ALT="$(fetch_secret SLACK_WEBHOOK_URL_ALT)"
ATTIO_API_ALT="$(fetch_secret ATTIO_API_ALT)"

# Authenticate Docker to Artifact Registry (idempotent).
gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet >/dev/null 2>&1 || true

echo "Pulling image: $IMAGE"
docker pull "$IMAGE"

echo "Stopping and removing any existing linkedin-bot container..."
docker stop linkedin-bot >/dev/null 2>&1 || true
docker rm linkedin-bot >/dev/null 2>&1 || true

echo "Starting linkedin-bot container..."
docker run -d \
    --name linkedin-bot \
    --restart unless-stopped \
    -p 8080:8080 \
    -v "$STATE_HOST_DIR:/app/state" \
    -e STATE_DIR=/app/state \
    -e ATTIO_API="$ATTIO_API" \
    -e GEMINI_API_KEY="$GEMINI_API_KEY" \
    -e APIFY_API="$APIFY_API" \
    -e PROXY_HOST="$PROXY_HOST" \
    -e PROXY_PORT="$PROXY_PORT" \
    -e PROXY_USERNAME="$PROXY_USERNAME" \
    -e PROXY_PASSWORD_BASE="$PROXY_PASSWORD_BASE" \
    -e USE_PROXY="$USE_PROXY" \
    -e SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL" \
    -e SLACK_WEBHOOK_URL_ALT="$SLACK_WEBHOOK_URL_ALT" \
    -e ATTIO_API_ALT="$ATTIO_API_ALT" \
    -e YATH_LINKEDIN_EMAIL="$YATH_LINKEDIN_EMAIL" \
    -e YATH_LINKEDIN_PASSWORD="$YATH_LINKEDIN_PASSWORD" \
    -e CLOUD_MODE=true \
    "$IMAGE"

echo "Container linkedin-bot started."
docker ps --filter name=linkedin-bot --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
