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
    key                  = "shared.terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}

# ------------------------------------------------------------------------------
# Resource Group for shared resources
# ------------------------------------------------------------------------------
module "resource_group" {
  source = "../modules/resource_group"

  name     = var.resource_group_name
  location = var.location

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Container Registry (shared across all environments)
# ------------------------------------------------------------------------------
module "container_registry" {
  source = "../modules/container_registry"

  name                = var.acr_name
  resource_group_name = module.resource_group.name
  location            = var.location
  sku                 = var.acr_sku

  tags = var.tags
}
