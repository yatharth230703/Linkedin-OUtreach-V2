output "instance_ip" {
  description = "External IP of the bot instance"
  value       = google_compute_instance.linkedin_bot.network_interface[0].access_config[0].nat_ip
}

output "api_url" {
  description = "Backend API URL"
  value       = "http://${google_compute_instance.linkedin_bot.network_interface[0].access_config[0].nat_ip}:8080"
}
