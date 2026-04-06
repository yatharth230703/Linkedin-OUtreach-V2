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
    # First-boot bootstrap for the LinkedIn bot VM.
    #
    # NOTE: This script only runs when the VM is created/recreated. Day-to-day
    # deploys go through scripts/redeploy.sh via the GitHub Actions workflow,
    # which does NOT recreate the VM. To prevent Terraform from recreating the
    # VM on every plan when this script is edited, this resource is configured
    # with `lifecycle.ignore_changes = [metadata_startup_script]` (see below).
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

    # Pre-create the persistent state subdirectories so the bind mount has
    # something to attach to. The container also creates these on its side.
    mkdir -p \
      "$MOUNT_POINT/state/cookies" \
      "$MOUNT_POINT/state/config" \
      "$MOUNT_POINT/state/flags" \
      "$MOUNT_POINT/state/status" \
      "$MOUNT_POINT/state/logs" \
      "$MOUNT_POINT/state/templates"

    # Drop the run_container.sh launcher into /opt so subsequent SSH-driven
    # redeploys can call it. The deploy workflow uploads its own copy on every
    # deploy, but having one here means the VM can self-heal on reboot.
    install -d /opt/linkedin-bot
    cat > /opt/linkedin-bot/run_container.sh <<'LAUNCHER'
    ${file("${path.module}/../scripts/run_container.sh")}
    LAUNCHER
    chmod +x /opt/linkedin-bot/run_container.sh

    # Authenticate Docker to Artifact Registry
    gcloud auth configure-docker ${var.region}-docker.pkg.dev --quiet

    # First-boot launch.
    IMAGE="${var.docker_image}" MOUNT_POINT="$MOUNT_POINT" /opt/linkedin-bot/run_container.sh
  SCRIPT

  tags = ["linkedin-bot"]

  service_account {
    email  = google_service_account.bot_sa.email
    scopes = ["cloud-platform"]
  }

  lifecycle {
    # Day-to-day deploys edit the container, not the VM. Ignore startup-script
    # diffs so editing main.tf or run_container.sh doesn't force-recreate the
    # VM (which would lose the running container, even though /mnt/bot-data
    # would survive).
    ignore_changes = [
      metadata_startup_script,
      boot_disk[0].initialize_params[0].image,
    ]
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

# Firewall rule to allow SSH from approved operator IPs.
# Manage this here so the rule survives any clean re-apply.
resource "google_compute_firewall" "ssh" {
  name    = "allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.ssh_allowed_ips
}

# Firewall rule to allow SSH from Google's IAP relay range.
# Required for GitHub Actions (and any other CI/operator without a static IP)
# to SSH via `gcloud compute ssh --tunnel-through-iap`.
resource "google_compute_firewall" "ssh_iap" {
  name    = "allow-ssh-iap"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # Google's documented IAP TCP forwarding source range.
  source_ranges = ["35.235.240.0/20"]
}
