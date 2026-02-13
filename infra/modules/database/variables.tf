variable "name" {
  description = "Name of the PostgreSQL Flexible Server"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "admin_user" {
  description = "Administrator username"
  type        = string
  sensitive   = true
}

variable "admin_password" {
  description = "Administrator password"
  type        = string
  sensitive   = true
}

variable "sku_name" {
  description = "SKU name for the PostgreSQL server (e.g., B_Standard_B1ms for dev, B_Standard_B2s for prod)"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  description = "Storage size in MB"
  type        = number
  default     = 32768
}

variable "database_name" {
  description = "Name of the application database"
  type        = string
  default     = "imggen"
}

variable "availability_zone" {
  description = "Availability zone for the server"
  type        = string
  default     = "1"
}

variable "backup_retention_days" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "geo_redundant_backup" {
  description = "Enable geo-redundant backup"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
