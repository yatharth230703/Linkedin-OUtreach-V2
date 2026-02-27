output "static_ip" {
  description = "Static IP of the bot instance"
  value       = google_compute_address.bot_ip.address
}

output "instance_ip" {
  description = "External IP of the bot instance (same as static_ip)"
  value       = google_compute_address.bot_ip.address
}

output "api_url" {
  description = "Backend API URL"
  value       = "http://${google_compute_address.bot_ip.address}:8080"
}
