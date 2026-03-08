terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Static IP for the bot VM
resource "google_compute_address" "bot_ip" {
  name   = "linkedin-bot-ip"
  region = var.region
}

# Service account for the bot VM
resource "google_service_account" "bot_sa" {
  account_id   = "linkedin-bot-sa"
  display_name = "LinkedIn Bot Service Account"
}

# Grant Secret Manager access to the service account
resource "google_project_iam_member" "bot_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.bot_sa.email}"
}

# Grant Artifact Registry reader access
resource "google_project_iam_member" "bot_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.bot_sa.email}"
}

# Persistent disk for cookies, config, and logs
resource "google_compute_disk" "bot_data" {
  name = "linkedin-bot-data"
  type = "pd-standard"
  size = 10
  zone = var.zone
}

# GCE instance running the bot in Docker on Ubuntu
resource "google_compute_instance" "linkedin_bot" {
  name         = "linkedin-bot"
  machine_type = "e2-medium"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
      size  = 30
      type  = "pd-standard"
    }
  }

  attached_disk {
    source      = google_compute_disk.bot_data.self_link
    device_name = "bot-data"
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.bot_ip.address
    }
  }

  metadata_startup_script = <<-SCRIPT
    #!/bin/bash
    set -e

    # Install Docker if not present
    if ! command -v docker &> /dev/null; then
      apt-get update
      apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
      apt-get update
      apt-get install -y docker-ce docker-ce-cli containerd.io
    fi

    # Mount persistent disk if not mounted
    MOUNT_POINT="/mnt/bot-data"
    DEVICE="/dev/disk/by-id/google-bot-data"
    if ! mountpoint -q "$MOUNT_POINT"; then
      mkdir -p "$MOUNT_POINT"
      # Format only if not already formatted
      if ! blkid "$DEVICE"; then
        mkfs.ext4 -F "$DEVICE"
      fi
      mount "$DEVICE" "$MOUNT_POINT"
      # Ensure it mounts on reboot
      echo "$DEVICE $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab
    fi
    mkdir -p "$MOUNT_POINT/browser_profiles"

    # Authenticate Docker to Artifact Registry
    gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet

    # Fetch secrets from Secret Manager
    ATTIO_API=$(gcloud secrets versions access latest --secret=ATTIO_API 2>/dev/null || echo "")
    GEMINI_API_KEY_TEST=$(gcloud secrets versions access latest --secret=GEMINI_API_KEY_TEST 2>/dev/null || echo "")
    APIFY_API=$(gcloud secrets versions access latest --secret=APIFY_API 2>/dev/null || echo "")
    PROXY_HOST=$(gcloud secrets versions access latest --secret=PROXY_HOST 2>/dev/null || echo "")
    PROXY_PORT=$(gcloud secrets versions access latest --secret=PROXY_PORT 2>/dev/null || echo "")
    PROXY_USERNAME=$(gcloud secrets versions access latest --secret=PROXY_USERNAME 2>/dev/null || echo "")
    PROXY_PASSWORD_BASE=$(gcloud secrets versions access latest --secret=PROXY_PASSWORD_BASE 2>/dev/null || echo "")
    USE_PROXY=$(gcloud secrets versions access latest --secret=USE_PROXY 2>/dev/null || echo "true")
    SLACK_WEBHOOK_URL=$(gcloud secrets versions access latest --secret=SLACK_WEBHOOK_URL 2>/dev/null || echo "")
    ATTIO_API_ALT=$(gcloud secrets versions access latest --secret=ATTIO_API_ALT 2>/dev/null || echo "")
    SLACK_WEBHOOK_URL_ALT=$(gcloud secrets versions access latest --secret=SLACK_WEBHOOK_URL_ALT 2>/dev/null || echo "")

    # Pull and run the container
    docker pull ${var.docker_image}
    docker stop linkedin-bot 2>/dev/null || true
    docker rm linkedin-bot 2>/dev/null || true
    docker run -d \
      --name linkedin-bot \
      --restart unless-stopped \
      -p 8080:8080 \
      -v "$MOUNT_POINT/browser_profiles:/app/Linkedin_cloud_bot_attio/playwright_bots/browser_profiles" \
      -e ATTIO_API="$ATTIO_API" \
      -e GEMINI_API_KEY_TEST="$GEMINI_API_KEY_TEST" \
      -e APIFY_API="$APIFY_API" \
      -e PROXY_HOST="$PROXY_HOST" \
      -e PROXY_PORT="$PROXY_PORT" \
      -e PROXY_USERNAME="$PROXY_USERNAME" \
      -e PROXY_PASSWORD_BASE="$PROXY_PASSWORD_BASE" \
      -e USE_PROXY="$USE_PROXY" \
      -e SLACK_WEBHOOK_URL="$SLACK_WEBHOOK_URL" \
      -e SLACK_WEBHOOK_URL_ALT="$SLACK_WEBHOOK_URL_ALT" \
      -e ATTIO_API_ALT="$ATTIO_API_ALT" \
      -e CLOUD_MODE=true \
      ${var.docker_image}
  SCRIPT

  tags = ["linkedin-bot"]

  service_account {
    email  = google_service_account.bot_sa.email
    scopes = ["cloud-platform"]
  }
}

# Firewall rule to allow API access
resource "google_compute_firewall" "bot_api" {
  name    = "allow-linkedin-bot-api"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["8080"]
  }

  # Restrict to your IP in production
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["linkedin-bot"]
}
