variable "environment_name" {
  description = "Name of the Container App Environment"
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

# --- Container Registry ---

variable "acr_login_server" {
  description = "ACR login server URL"
  type        = string
}

variable "acr_username" {
  description = "ACR admin username"
  type        = string
}

variable "acr_password" {
  description = "ACR admin password"
  type        = string
  sensitive   = true
}

# --- Images ---

variable "backend_image" {
  description = "Backend container image name (without registry prefix)"
  type        = string
  default     = "imggen-backend"
}

variable "backend_image_tag" {
  description = "Backend container image tag"
  type        = string
  default     = "latest"
}

# --- Backend scaling ---

variable "backend_min_replicas" {
  description = "Minimum replicas for backend"
  type        = number
  default     = 1
}

variable "backend_max_replicas" {
  description = "Maximum replicas for backend"
  type        = number
  default     = 3
}

variable "backend_cpu" {
  description = "CPU allocation for backend container"
  type        = number
  default     = 0.5
}

variable "backend_memory" {
  description = "Memory allocation for backend container"
  type        = string
  default     = "1Gi"
}

# --- Celery Worker (default queue) scaling ---

variable "celery_worker_min_replicas" {
  description = "Minimum replicas for celery worker"
  type        = number
  default     = 1
}

variable "celery_worker_max_replicas" {
  description = "Maximum replicas for celery worker"
  type        = number
  default     = 2
}

variable "celery_worker_cpu" {
  description = "CPU allocation for celery worker container"
  type        = number
  default     = 0.5
}

variable "celery_worker_memory" {
  description = "Memory allocation for celery worker container"
  type        = string
  default     = "1Gi"
}

variable "celery_worker_concurrency" {
  description = "Concurrency level for default celery worker"
  type        = number
  default     = 2
}

# --- Celery Worker (clustering queue) scaling ---

variable "celery_clustering_min_replicas" {
  description = "Minimum replicas for celery clustering worker"
  type        = number
  default     = 1
}

variable "celery_clustering_max_replicas" {
  description = "Maximum replicas for celery clustering worker"
  type        = number
  default     = 1
}

variable "celery_clustering_cpu" {
  description = "CPU allocation for celery clustering container"
  type        = number
  default     = 1.0
}

variable "celery_clustering_memory" {
  description = "Memory allocation for celery clustering container"
  type        = string
  default     = "2Gi"
}

# --- Celery Worker (generation queue) scaling ---

variable "celery_generation_min_replicas" {
  description = "Minimum replicas for celery generation worker"
  type        = number
  default     = 1
}

variable "celery_generation_max_replicas" {
  description = "Maximum replicas for celery generation worker"
  type        = number
  default     = 2
}

variable "celery_generation_cpu" {
  description = "CPU allocation for celery generation container"
  type        = number
  default     = 0.5
}

variable "celery_generation_memory" {
  description = "Memory allocation for celery generation container"
  type        = string
  default     = "1Gi"
}

variable "celery_generation_concurrency" {
  description = "Concurrency level for generation celery worker"
  type        = number
  default     = 2
}

# --- Environment Variables ---

variable "environment_variables" {
  description = "Map of environment variables for all containers (non-secret)"
  type        = map(string)
  default     = {}
}

variable "secret_environment_variables" {
  description = "Map of environment variable name to secret name for secret references"
  type        = map(string)
  default     = {}
}

variable "app_secrets" {
  description = "Map of secret name to secret value for Container App secrets"
  type        = map(string)
  default     = {}
  sensitive   = true
}

# --- Logging ---

variable "log_retention_days" {
  description = "Log Analytics workspace retention in days"
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
