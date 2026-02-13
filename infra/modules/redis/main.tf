resource "azurerm_redis_cache" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  capacity            = var.capacity
  family              = var.family
  sku_name            = var.sku_name

  minimum_tls_version = "1.2"
  non_ssl_port_enabled = false

  redis_configuration {
    maxmemory_policy = var.maxmemory_policy
  }

  tags = var.tags
}
