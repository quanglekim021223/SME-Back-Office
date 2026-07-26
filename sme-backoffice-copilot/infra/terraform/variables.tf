variable "project" {
  description = "Short, lowercase project name used in Azure resource names."
  type        = string
  default     = "smebackoffice"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "staging"
}

variable "location" {
  description = "Azure region for the recreated environment."
  type        = string
  default     = "southeastasia"
}

variable "resource_group_name" {
  description = "Resource group Terraform will create and own. Use a new name unless importing existing resources."
  type        = string
  default     = "rg-sme-backoffice-staging"
}

variable "frontend_origin" {
  description = "Allowed production frontend origin for API CORS."
  type        = string
  default     = "https://sme-back-office.vercel.app"
}

variable "enable_container_apps" {
  description = "Create API, worker, and dispatcher only after an application image is available in ACR."
  type        = bool
  default     = false
}

variable "container_image" {
  description = "Immutable ACR image reference used for the initial Container App revision."
  type        = string
  default     = null
  nullable    = true
}

variable "database_url" {
  description = "Neon SQLAlchemy asyncpg URL with TLS enabled. Passed only during the runtime apply."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "celery_broker_url" {
  description = "Upstash rediss URL for Celery broker database 0."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "celery_result_backend_url" {
  description = "Upstash rediss URL for Celery result backend database 1."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "provider_rate_limit_redis_url" {
  description = "Upstash rediss URL for provider rate limiting."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "worker_min_replicas" {
  description = "Minimum worker replicas. Keep 1 for the current Redis worker model."
  type        = number
  default     = 1
}

variable "worker_max_replicas" {
  description = "Maximum worker replicas."
  type        = number
  default     = 1
}

variable "dispatcher_min_replicas" {
  description = "Minimum dispatcher replicas. The current database-polling dispatcher needs one live replica."
  type        = number
  default     = 1
}

variable "dispatcher_max_replicas" {
  description = "Maximum dispatcher replicas."
  type        = number
  default     = 1
}
