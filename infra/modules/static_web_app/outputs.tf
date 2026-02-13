output "default_host_name" {
  description = "Default hostname of the Static Web App"
  value       = azurerm_static_web_app.this.default_host_name
}

output "api_key" {
  description = "API key for deployment of the Static Web App"
  value       = azurerm_static_web_app.this.api_key
  sensitive   = true
}

output "id" {
  description = "ID of the Static Web App"
  value       = azurerm_static_web_app.this.id
}
