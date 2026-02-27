variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "asia-south1"
}

variable "zone" {
  description = "GCP zone"
  type        = string
  default     = "asia-south1-a"
}

variable "docker_image" {
  description = "Docker image for the bot (e.g. asia-south1-docker.pkg.dev/PROJECT/linkedin-bot/bot:latest)"
  type        = string
}
