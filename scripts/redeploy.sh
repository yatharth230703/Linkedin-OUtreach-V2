#!/bin/bash
# redeploy.sh — invoked on the VM by the GitHub Actions deploy workflow.
#
# Responsibilities:
#   1. Tag the new image as :latest locally and call run_container.sh
#   2. Append a structured audit entry to the deploy log on the persistent disk
#   3. Health-check the API after the container is up
#
# Inputs (positional):
#   $1   image_tag   The git SHA / tag the workflow built and pushed
#                    (e.g. asia-south1-docker.pkg.dev/.../bot:abc1234)
#
# Exit codes:
#   0   success
#   1   bad arguments
#   2   docker pull/run failed
#   3   health check failed

set -euo pipefail

IMAGE_TAG="${1:-}"
if [ -z "$IMAGE_TAG" ]; then
    echo "usage: $0 <full-image-tag>" >&2
    exit 1
fi

MOUNT_POINT="${MOUNT_POINT:-/mnt/bot-data}"
STATE_HOST_DIR="$MOUNT_POINT/state"
LOG_DIR="$STATE_HOST_DIR/logs"
DEPLOY_LOG="$LOG_DIR/deploy.log"

mkdir -p "$LOG_DIR"

# Helper: append a timestamped, structured line to the deploy log.
log_line() {
    local level="$1"
    shift
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [$level] $*" | tee -a "$DEPLOY_LOG"
}

# Trap any failure so we always log it before exiting.
on_error() {
    local exit_code=$?
    log_line ERROR "Deploy failed for image=$IMAGE_TAG with exit code $exit_code"
    exit "$exit_code"
}
trap on_error ERR

log_line INFO "===== Deploy started ====="
log_line INFO "image=$IMAGE_TAG"
log_line INFO "user=$(whoami) host=$(hostname)"

# Capture the currently-running image so we can record what we're rolling forward from.
PREV_IMAGE="$(sudo docker inspect linkedin-bot --format='{{.Config.Image}}' 2>/dev/null || echo 'none')"
log_line INFO "previous_image=$PREV_IMAGE"

# Use the shared launcher to actually swap the container.
# Clean up old Docker images before pulling the new one to avoid disk-full.
# Each image is ~2.3 GB; the 30 GB boot disk fills up after ~10 deploys.
log_line INFO "Pruning old Docker images..."
sudo docker image prune -a -f --filter "until=24h" >/dev/null 2>&1 || true

log_line INFO "Calling run_container.sh"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
sudo IMAGE="$IMAGE_TAG" MOUNT_POINT="$MOUNT_POINT" "$SCRIPT_DIR/run_container.sh" 2>&1 | tee -a "$DEPLOY_LOG"

# Tag the new image as :latest locally for consistency.
sudo docker tag "$IMAGE_TAG" asia-south1-docker.pkg.dev/optimum-beach-489223-h7/linkedin-bot/bot:latest || true

# Health check: poll the API for up to 60 seconds.
log_line INFO "Running health check on http://localhost:8080/api/status"
HEALTH_OK=false
for i in $(seq 1 12); do
    if curl -fsS -m 5 -H "X-Api-Key: linkedin-bot-beta-2024" \
        "http://localhost:8080/api/status?account_name=yatharth%20bisht" >/dev/null 2>&1; then
        HEALTH_OK=true
        break
    fi
    sleep 5
done

if [ "$HEALTH_OK" = "true" ]; then
    log_line INFO "Health check PASSED"
    log_line INFO "===== Deploy completed successfully ====="
    exit 0
else
    log_line ERROR "Health check FAILED after 60s"
    log_line ERROR "===== Deploy completed with failure ====="
    exit 3
fi
