variable "location" {
  description = "Azure region for shared resources"
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the shared resource group"
  type        = string
  default     = "rg-imggen-shared"
}

variable "acr_name" {
  description = "Name of the Azure Container Registry (globally unique, alphanumeric only)"
  type        = string
  default     = "acrimggen"
}

variable "acr_sku" {
  description = "SKU for the Azure Container Registry"
  type        = string
  default     = "Basic"
}

variable "tags" {
  description = "Tags to apply to all shared resources"
  type        = map(string)
  default = {
    project     = "image-model-generator"
    environment = "shared"
    managed_by  = "terraform"
  }
}
