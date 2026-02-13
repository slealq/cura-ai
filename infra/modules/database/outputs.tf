output "fqdn" {
  description = "Fully qualified domain name of the PostgreSQL server"
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "connection_string" {
  description = "PostgreSQL connection string"
  value       = "postgresql://${var.admin_user}:${var.admin_password}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/${var.database_name}?sslmode=require"
  sensitive   = true
}

output "server_id" {
  description = "ID of the PostgreSQL server"
  value       = azurerm_postgresql_flexible_server.this.id
}

output "server_name" {
  description = "Name of the PostgreSQL server"
  value       = azurerm_postgresql_flexible_server.this.name
}

output "database_name" {
  description = "Name of the application database"
  value       = azurerm_postgresql_flexible_server_database.app.name
}
