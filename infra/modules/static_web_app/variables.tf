variable "name" {
  description = "Name of the Static Web App"
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

variable "sku_tier" {
  description = "SKU tier for the Static Web App (Free, Standard)"
  type        = string
  default     = "Free"
}

variable "sku_size" {
  description = "SKU size for the Static Web App (Free, Standard)"
  type        = string
  default     = "Free"
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
