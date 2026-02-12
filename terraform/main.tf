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

# GCE instance running the bot in Docker
resource "google_compute_instance" "linkedin_bot" {
  name         = "linkedin-bot"
  machine_type = "e2-medium"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "projects/cos-cloud/global/images/family/cos-stable"
      size  = 30
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP
    }
  }

  metadata = {
    gce-container-declaration = <<-EOF
      spec:
        containers:
          - image: ${var.docker_image}
            name: linkedin-bot
            ports:
              - containerPort: 8080
                hostPort: 8080
            volumeMounts:
              - name: bot-data
                mountPath: /app/backend
                readOnly: false
        volumes:
          - name: bot-data
            emptyDir: {}
        restartPolicy: Always
    EOF
  }

  tags = ["linkedin-bot"]

  service_account {
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
