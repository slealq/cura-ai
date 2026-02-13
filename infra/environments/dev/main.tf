terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-imggen-tfstate"
    storage_account_name = "stimggentfstate"
    container_name       = "tfstate"
    key                  = "dev.terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "current" {}

# Retrieve shared ACR outputs
data "terraform_remote_state" "shared" {
  backend = "azurerm"

  config = {
    resource_group_name  = "rg-imggen-tfstate"
    storage_account_name = "stimggentfstate"
    container_name       = "tfstate"
    key                  = "shared.terraform.tfstate"
  }
}

locals {
  environment = "dev"
  tags = {
    project     = "image-model-generator"
    environment = local.environment
    managed_by  = "terraform"
  }
}

# ------------------------------------------------------------------------------
# Resource Group
# ------------------------------------------------------------------------------
module "resource_group" {
  source = "../../modules/resource_group"

  name     = var.resource_group_name
  location = var.location

  tags = local.tags
}

# ------------------------------------------------------------------------------
# Storage Account
# ------------------------------------------------------------------------------
module "storage" {
  source = "../../modules/storage"

  name                = var.storage_account_name
  resource_group_name = module.resource_group.name
  location            = var.location
  container_name      = "images"

  cors_allowed_origins = ["*"]

  tags = local.tags
}

# ------------------------------------------------------------------------------
# PostgreSQL Database with pgvector
# ------------------------------------------------------------------------------
module "database" {
  source = "../../modules/database"

  name                = var.database_name
  resource_group_name = module.resource_group.name
  location            = var.db_location
  admin_user          = var.db_admin_user
  admin_password      = var.db_admin_password
  sku_name            = var.db_sku_name
  storage_mb          = var.db_storage_mb

  tags = local.tags
}

# ------------------------------------------------------------------------------
# Redis Cache
# ------------------------------------------------------------------------------
module "redis" {
  source = "../../modules/redis"

  name                = var.redis_name
  resource_group_name = module.resource_group.name
  location            = var.location
  sku_name            = var.redis_sku_name
  capacity            = var.redis_capacity
  family              = var.redis_family

  tags = local.tags
}

# ------------------------------------------------------------------------------
# Container Apps (Backend + Celery Workers)
# ------------------------------------------------------------------------------
module "container_apps" {
  source = "../../modules/container_apps"

  environment_name    = var.container_app_env_name
  resource_group_name = module.resource_group.name
  location            = var.location

  acr_login_server = data.terraform_remote_state.shared.outputs.acr_login_server
  acr_username     = data.terraform_remote_state.shared.outputs.acr_admin_username
  acr_password     = data.terraform_remote_state.shared.outputs.acr_admin_password

  backend_image     = "imggen-backend"
  backend_image_tag = var.image_tag

  # Dev scaling: minimal replicas
  backend_min_replicas = 1
  backend_max_replicas = 3
  backend_cpu          = 0.5
  backend_memory       = "1Gi"

  celery_worker_min_replicas = 1
  celery_worker_max_replicas = 2
  celery_worker_cpu          = 0.5
  celery_worker_memory       = "1Gi"

  celery_clustering_min_replicas = 1
  celery_clustering_max_replicas = 1
  celery_clustering_cpu          = 1.0
  celery_clustering_memory       = "2Gi"

  celery_generation_min_replicas = 1
  celery_generation_max_replicas = 2
  celery_generation_cpu          = 0.5
  celery_generation_memory       = "1Gi"

  environment_variables = {
    DEFAULT_VISION_PROVIDER  = "openai"
    ENVIRONMENT              = "dev"
    STORAGE_BACKEND          = "azure"
    AZURE_STORAGE_CONTAINER  = "images"
  }

  secret_environment_variables = {
    DATABASE_URL                       = "database-url"
    REDIS_URL                          = "redis-url"
    CELERY_BROKER_URL                  = "celery-broker-url"
    AZURE_STORAGE_CONNECTION_STRING    = "azure-storage-connection"
    JWT_SECRET_KEY                     = "jwt-secret"
    OPENAI_API_KEY                     = "openai-api-key"
    ANTHROPIC_API_KEY                  = "anthropic-api-key"
    FAL_API_KEY                        = "fal-api-key"
  }

  app_secrets = {
    "database-url"              = module.database.connection_string
    "redis-url"                 = module.redis.connection_string
    "celery-broker-url"         = module.redis.connection_string
    "azure-storage-connection"  = module.storage.connection_string
    "jwt-secret"                = var.jwt_secret_key
    "openai-api-key"            = var.openai_api_key
    "anthropic-api-key"         = var.anthropic_api_key
    "fal-api-key"               = var.fal_api_key
  }

  tags = local.tags
}

# ------------------------------------------------------------------------------
# Static Web App (Frontend)
# ------------------------------------------------------------------------------
module "static_web_app" {
  source = "../../modules/static_web_app"

  name                = var.static_web_app_name
  resource_group_name = module.resource_group.name
  location            = var.swa_location
  sku_tier            = "Free"
  sku_size            = "Free"

  tags = local.tags
}

# ------------------------------------------------------------------------------
# Key Vault
# ------------------------------------------------------------------------------
module "key_vault" {
  source = "../../modules/key_vault"

  name                = var.key_vault_name
  resource_group_name = module.resource_group.name
  location            = var.location
  tenant_id           = data.azurerm_client_config.current.tenant_id

  tags = local.tags
}
