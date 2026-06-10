output "web_url" {
  description = "Open this in a browser"
  value       = "http://localhost:${var.web_port}"
}

output "stats_url" {
  value = "http://localhost:${var.web_port}/stats.html"
}

output "api_health_url" {
  value = "http://localhost:${var.api_port}/api/health"
}
