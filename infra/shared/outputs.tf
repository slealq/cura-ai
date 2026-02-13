output "acr_login_server" {
  description = "ACR login server URL"
  value       = module.container_registry.login_server
}

output "acr_admin_username" {
  description = "ACR admin username"
  value       = module.container_registry.admin_username
}

output "acr_admin_password" {
  description = "ACR admin password"
  value       = module.container_registry.admin_password
  sensitive   = true
}

output "acr_name" {
  description = "Name of the ACR"
  value       = module.container_registry.name
}

output "resource_group_name" {
  description = "Name of the shared resource group"
  value       = module.resource_group.name
}
