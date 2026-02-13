output "resource_group_name" {
  description = "Name of the dev resource group"
  value       = module.resource_group.name
}

# --- Storage ---

output "storage_account_name" {
  description = "Storage account name"
  value       = module.storage.account_name
}

output "storage_connection_string" {
  description = "Storage account connection string"
  value       = module.storage.connection_string
  sensitive   = true
}

# --- Database ---

output "database_fqdn" {
  description = "PostgreSQL server FQDN"
  value       = module.database.fqdn
}

output "database_connection_string" {
  description = "PostgreSQL connection string"
  value       = module.database.connection_string
  sensitive   = true
}

# --- Redis ---

output "redis_hostname" {
  description = "Redis cache hostname"
  value       = module.redis.hostname
}

output "redis_connection_string" {
  description = "Redis connection string (rediss:// with TLS)"
  value       = module.redis.connection_string
  sensitive   = true
}

# --- Container Apps ---

output "backend_url" {
  description = "Backend API URL"
  value       = module.container_apps.backend_url
}

output "backend_fqdn" {
  description = "Backend FQDN"
  value       = module.container_apps.backend_fqdn
}

# --- Static Web App ---

output "frontend_url" {
  description = "Frontend URL"
  value       = "https://${module.static_web_app.default_host_name}"
}

output "static_web_app_api_key" {
  description = "Static Web App deployment API key"
  value       = module.static_web_app.api_key
  sensitive   = true
}

# --- Key Vault ---

output "key_vault_uri" {
  description = "Key Vault URI"
  value       = module.key_vault.vault_uri
}
