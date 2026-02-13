location            = "eastus"
resource_group_name = "rg-imggen-shared"
acr_name            = "acrimggen"
acr_sku             = "Basic"

tags = {
  project     = "image-model-generator"
  environment = "shared"
  managed_by  = "terraform"
}
