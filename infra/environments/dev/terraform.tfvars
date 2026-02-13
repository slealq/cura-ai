location             = "eastus"
db_location          = "eastus2"
swa_location         = "eastus2"
resource_group_name  = "rg-imggen-dev"
storage_account_name = "stimggendev"
database_name        = "psql-imggen-dev2"
db_sku_name          = "B_Standard_B1ms"
db_storage_mb        = 32768
redis_name           = "redis-imggen-dev"
redis_sku_name       = "Basic"
redis_capacity       = 0
redis_family         = "C"
container_app_env_name = "cae-imggen-dev"
static_web_app_name  = "swa-imggen-dev"
key_vault_name       = "kv-imggen-dev"
image_tag            = "latest"

# Sensitive variables should be set via environment variables:
#   TF_VAR_db_admin_user
#   TF_VAR_db_admin_password
#   TF_VAR_jwt_secret_key
#   TF_VAR_openai_api_key
#   TF_VAR_anthropic_api_key
#   TF_VAR_fal_api_key
