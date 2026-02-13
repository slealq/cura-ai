resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.environment_name}-logs"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  tags = var.tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = var.environment_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Backend Container App
# ------------------------------------------------------------------------------
resource "azurerm_container_app" "backend" {
  name                         = "${var.environment_name}-backend"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "registry-password"
    value = var.acr_password
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(var.app_secrets)))
    content {
      name  = secret.value
      value = var.app_secrets[secret.value]
    }
  }

  registry {
    server               = var.acr_login_server
    username             = var.acr_username
    password_secret_name = "registry-password"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.backend_min_replicas
    max_replicas = var.backend_max_replicas

    container {
      name   = "backend"
      image  = "${var.acr_login_server}/${var.backend_image}:${var.backend_image_tag}"
      cpu    = var.backend_cpu
      memory = var.backend_memory

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_environment_variables
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Celery Worker Container App (default queue)
# ------------------------------------------------------------------------------
resource "azurerm_container_app" "celery_worker" {
  name                         = "${var.environment_name}-celery-worker"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "registry-password"
    value = var.acr_password
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(var.app_secrets)))
    content {
      name  = secret.value
      value = var.app_secrets[secret.value]
    }
  }

  registry {
    server               = var.acr_login_server
    username             = var.acr_username
    password_secret_name = "registry-password"
  }

  template {
    min_replicas = var.celery_worker_min_replicas
    max_replicas = var.celery_worker_max_replicas

    container {
      name   = "celery-worker"
      image  = "${var.acr_login_server}/${var.backend_image}:${var.backend_image_tag}"
      cpu    = var.celery_worker_cpu
      memory = var.celery_worker_memory

      command = [
        "celery", "-A", "app.workers.celery_app", "worker",
        "--loglevel=info",
        "--concurrency=${var.celery_worker_concurrency}"
      ]

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_environment_variables
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Celery Worker - Clustering Queue
# ------------------------------------------------------------------------------
resource "azurerm_container_app" "celery_worker_clustering" {
  name                         = "${var.environment_name}-celery-clustering"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "registry-password"
    value = var.acr_password
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(var.app_secrets)))
    content {
      name  = secret.value
      value = var.app_secrets[secret.value]
    }
  }

  registry {
    server               = var.acr_login_server
    username             = var.acr_username
    password_secret_name = "registry-password"
  }

  template {
    min_replicas = var.celery_clustering_min_replicas
    max_replicas = var.celery_clustering_max_replicas

    container {
      name   = "celery-clustering"
      image  = "${var.acr_login_server}/${var.backend_image}:${var.backend_image_tag}"
      cpu    = var.celery_clustering_cpu
      memory = var.celery_clustering_memory

      command = [
        "celery", "-A", "app.workers.celery_app", "worker",
        "-Q", "clustering",
        "--loglevel=info",
        "--concurrency=1"
      ]

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_environment_variables
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Celery Worker - Generation Queue
# ------------------------------------------------------------------------------
resource "azurerm_container_app" "celery_worker_generation" {
  name                         = "${var.environment_name}-celery-generation"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "registry-password"
    value = var.acr_password
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(var.app_secrets)))
    content {
      name  = secret.value
      value = var.app_secrets[secret.value]
    }
  }

  registry {
    server               = var.acr_login_server
    username             = var.acr_username
    password_secret_name = "registry-password"
  }

  template {
    min_replicas = var.celery_generation_min_replicas
    max_replicas = var.celery_generation_max_replicas

    container {
      name   = "celery-generation"
      image  = "${var.acr_login_server}/${var.backend_image}:${var.backend_image_tag}"
      cpu    = var.celery_generation_cpu
      memory = var.celery_generation_memory

      command = [
        "celery", "-A", "app.workers.celery_app", "worker",
        "-Q", "generation",
        "--loglevel=info",
        "--concurrency=${var.celery_generation_concurrency}"
      ]

      dynamic "env" {
        for_each = var.environment_variables
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_environment_variables
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = var.tags
}
