variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the prod resource group"
  type        = string
  default     = "rg-imggen-prod"
}

# --- Storage ---

variable "storage_account_name" {
  description = "Storage account name (globally unique, lowercase, no hyphens, max 24 chars)"
  type        = string
  default     = "stimggenprod"
}

# --- Database ---

variable "database_name" {
  description = "PostgreSQL Flexible Server name"
  type        = string
  default     = "psql-imggen-prod"
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
  default     = "B_Standard_B2s"
}

variable "db_storage_mb" {
  description = "Database storage in MB"
  type        = number
  default     = 65536
}

# --- Redis ---

variable "redis_name" {
  description = "Redis cache name"
  type        = string
  default     = "redis-imggen-prod"
}

variable "redis_sku_name" {
  description = "Redis SKU"
  type        = string
  default     = "Standard"
}

variable "redis_capacity" {
  description = "Redis cache capacity"
  type        = number
  default     = 1
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
  default     = "cae-imggen-prod"
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
  default     = "swa-imggen-prod"
}

# --- Key Vault ---

variable "key_vault_name" {
  description = "Key Vault name"
  type        = string
  default     = "kv-imggen-prod"
}

# --- CORS ---

variable "cors_allowed_origins" {
  description = "Allowed CORS origins for the storage account"
  type        = list(string)
  default     = []
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
