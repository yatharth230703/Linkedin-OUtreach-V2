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

variable "ssh_allowed_ips" {
  description = "CIDR ranges allowed to SSH into the bot VM. Add operator IPs as needed."
  type        = list(string)
  default = [
    "103.212.156.149/32",
    "103.212.156.235/32",
  ]
}
