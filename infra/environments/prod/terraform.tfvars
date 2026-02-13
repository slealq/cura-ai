location             = "eastus"
resource_group_name  = "rg-imggen-prod"
storage_account_name = "stimggenprod"
database_name        = "psql-imggen-prod"
db_sku_name          = "B_Standard_B2s"
db_storage_mb        = 65536
redis_name           = "redis-imggen-prod"
redis_sku_name       = "Standard"
redis_capacity       = 1
redis_family         = "C"
container_app_env_name = "cae-imggen-prod"
static_web_app_name  = "swa-imggen-prod"
key_vault_name       = "kv-imggen-prod"
image_tag            = "latest"

cors_allowed_origins = []

# Sensitive variables should be set via environment variables:
#   TF_VAR_db_admin_user
#   TF_VAR_db_admin_password
#   TF_VAR_jwt_secret_key
#   TF_VAR_openai_api_key
#   TF_VAR_anthropic_api_key
#   TF_VAR_fal_api_key
