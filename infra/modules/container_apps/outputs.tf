output "backend_fqdn" {
  description = "FQDN of the backend Container App"
  value       = azurerm_container_app.backend.ingress[0].fqdn
}

output "backend_url" {
  description = "Full HTTPS URL of the backend Container App"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "environment_id" {
  description = "ID of the Container App Environment"
  value       = azurerm_container_app_environment.this.id
}

output "log_analytics_workspace_id" {
  description = "ID of the Log Analytics workspace"
  value       = azurerm_log_analytics_workspace.this.id
}

output "backend_id" {
  description = "ID of the backend Container App"
  value       = azurerm_container_app.backend.id
}

output "celery_worker_id" {
  description = "ID of the celery worker Container App"
  value       = azurerm_container_app.celery_worker.id
}

output "celery_clustering_id" {
  description = "ID of the celery clustering Container App"
  value       = azurerm_container_app.celery_worker_clustering.id
}

output "celery_generation_id" {
  description = "ID of the celery generation Container App"
  value       = azurerm_container_app.celery_worker_generation.id
}
