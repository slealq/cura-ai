variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the dev resource group"
  type        = string
  default     = "rg-imggen-dev"
}

# --- Storage ---

variable "storage_account_name" {
  description = "Storage account name (globally unique, lowercase, no hyphens, max 24 chars)"
  type        = string
  default     = "stimggendev"
}

# --- Database ---

variable "database_name" {
  description = "PostgreSQL Flexible Server name"
  type        = string
  default     = "psql-imggen-dev"
}

variable "db_location" {
  description = "Azure region for PostgreSQL (may differ from main location due to subscription restrictions)"
  type        = string
  default     = "eastus"
}

variable "db_admin_user" {
  description = "Database administrator username"
  type        = string
  sensitive   = true
}

variable "db_admin_password" {
  description = "Database administrator password"
  type        = string
  sensitive   = true
}

variable "db_sku_name" {
  description = "Database SKU"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "db_storage_mb" {
  description = "Database storage in MB"
  type        = number
  default     = 32768
}

# --- Redis ---

variable "redis_name" {
  description = "Redis cache name"
  type        = string
  default     = "redis-imggen-dev"
}

variable "redis_sku_name" {
  description = "Redis SKU"
  type        = string
  default     = "Basic"
}

variable "redis_capacity" {
  description = "Redis cache capacity"
  type        = number
  default     = 0
}

variable "redis_family" {
  description = "Redis cache family"
  type        = string
  default     = "C"
}

# --- Container Apps ---

variable "container_app_env_name" {
  description = "Container App Environment name"
  type        = string
  default     = "cae-imggen-dev"
}

variable "image_tag" {
  description = "Container image tag to deploy"
  type        = string
  default     = "latest"
}

# --- Static Web App ---

variable "static_web_app_name" {
  description = "Static Web App name"
  type        = string
  default     = "swa-imggen-dev"
}

variable "swa_location" {
  description = "Azure region for Static Web Apps (limited availability: westus2, centralus, eastus2, westeurope, eastasia)"
  type        = string
  default     = "eastus2"
}

# --- Key Vault ---

variable "key_vault_name" {
  description = "Key Vault name"
  type        = string
  default     = "kv-imggen-dev"
}

# --- Secrets (passed via environment or .tfvars, never committed) ---

variable "jwt_secret_key" {
  description = "JWT secret key for authentication"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "anthropic_api_key" {
  description = "Anthropic API key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "fal_api_key" {
  description = "fal.ai API key"
  type        = string
  sensitive   = true
  default     = ""
}
