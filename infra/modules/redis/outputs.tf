output "hostname" {
  description = "Hostname of the Redis cache"
  value       = azurerm_redis_cache.this.hostname
}

output "primary_access_key" {
  description = "Primary access key for the Redis cache"
  value       = azurerm_redis_cache.this.primary_access_key
  sensitive   = true
}

output "connection_string" {
  description = "Redis connection string in rediss:// format with TLS on port 6380"
  value       = "rediss://:${azurerm_redis_cache.this.primary_access_key}@${azurerm_redis_cache.this.hostname}:${azurerm_redis_cache.this.ssl_port}"
  sensitive   = true
}

output "ssl_port" {
  description = "SSL port of the Redis cache"
  value       = azurerm_redis_cache.this.ssl_port
}

output "id" {
  description = "ID of the Redis cache"
  value       = azurerm_redis_cache.this.id
}
