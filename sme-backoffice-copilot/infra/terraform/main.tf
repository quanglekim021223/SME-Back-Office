locals {
  name_prefix = "${var.project}-${var.environment}"
  name_compact = replace(
    lower("${var.project}${var.environment}"),
    "/[^a-z0-9]/",
    ""
  )

  common_environment = {
    APP_ENV                                  = var.environment
    APP_DEBUG                                = "false"
    APP_API_PREFIX                           = "/api/v1"
    LOG_FORMAT                               = "json"
    WORKFLOW_QUEUE_MODE                      = "celery"
    DOCUMENT_STORAGE_PROVIDER                = "azure_blob"
    AZURE_STORAGE_CONTAINER                  = azurerm_storage_container.documents.name
    AZURE_STORAGE_BLOB_ENDPOINT              = azurerm_storage_account.documents.primary_blob_endpoint
    OCR_PROVIDER                             = "azure_di"
    AZURE_DI_ENDPOINT                        = azurerm_cognitive_account.document_intelligence.endpoint
    AZURE_DI_MODEL_ID                        = "prebuilt-invoice"
    OCR_PREPROCESSING_ENABLED                = "true"
    OCR_PREPROCESSING_DESKEW                 = "true"
    OCR_PREPROCESSING_DENOISE                = "false"
    OCR_PREPROCESSING_BINARIZE               = "false"
    OCR_PREPROCESSING_UPSCALE_MIN_PX         = "0"
    OCR_PREPROCESSING_CLAHE_CLIP_LIMIT       = "2.0"
    OCR_PREPROCESSING_CLAHE_TILE_GRID_SIZE   = "8"
    CELERY_WORKER_CONCURRENCY                = "2"
    CELERY_TASK_MAX_RETRIES                  = "3"
    CELERY_RETRY_BACKOFF_SECONDS             = "1.0"
    CELERY_BROKER_POLLING_INTERVAL_SECONDS   = "30"
    OUTBOX_POLL_INTERVAL_SECONDS             = "5"
    OUTBOX_BATCH_SIZE                        = "50"
    OUTBOX_RETRY_BACKOFF_SECONDS             = "1.0"
    WORKFLOW_JOB_HEARTBEAT_SECONDS           = "10"
    WORKFLOW_JOB_LEASE_SECONDS               = "45"
    PROVIDER_RATE_LIMIT_ENABLED              = "true"
    PROVIDER_OCR_REQUESTS_PER_SECOND         = "5"
    PROVIDER_LLM_REQUESTS_PER_SECOND         = "5"
    PROVIDER_RATE_LIMIT_WAIT_TIMEOUT_SECONDS = "30"
  }
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    application = var.project
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${local.name_prefix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name_prefix}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_container_registry" "main" {
  name                = "acr${local.name_compact}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_storage_account" "documents" {
  name                            = "st${local.name_compact}${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_storage_container" "documents" {
  name                  = "documents"
  storage_account_id    = azurerm_storage_account.documents.id
  container_access_type = "private"
}

resource "azurerm_cognitive_account" "document_intelligence" {
  name                  = "di-${local.name_prefix}-${random_string.suffix.result}"
  location              = azurerm_resource_group.main.location
  resource_group_name   = azurerm_resource_group.main.name
  kind                  = "FormRecognizer"
  sku_name              = "S0"
  custom_subdomain_name = "di-${local.name_prefix}-${random_string.suffix.result}"

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_user_assigned_identity" "runtime" {
  name                = "id-${local.name_prefix}-runtime"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_role_assignment" "runtime_blob_contributor" {
  scope                = azurerm_storage_account.documents.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.runtime.principal_id
}

# This is the ABAC-compatible equivalent of AcrPull for the registry configuration
# already used by this subscription.
resource "azurerm_role_assignment" "runtime_acr_reader" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "Container Registry Repository Reader"
  principal_id         = azurerm_user_assigned_identity.runtime.principal_id
}

# GitHub Actions authenticates with OIDC. No Azure client secret is created.
resource "azurerm_user_assigned_identity" "github_deployment" {
  name                = "id-github-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_federated_identity_credential" "github_main" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.github_deployment.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:quanglekim021223/SME-Back-Office:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github_resource_group_contributor" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id
}

resource "azurerm_role_assignment" "github_acr_writer" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "Container Registry Repository Writer"
  principal_id         = azurerm_user_assigned_identity.github_deployment.principal_id
}

resource "azurerm_container_app" "api" {
  count = var.enable_container_apps ? 1 : 0

  name                         = "ca-${var.project}-api-${var.environment}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.runtime.id
  }

  secret {
    name  = "database-url"
    value = var.database_url
  }

  secret {
    name  = "celery-broker-url"
    value = var.celery_broker_url
  }

  secret {
    name  = "celery-result-backend-url"
    value = var.celery_result_backend_url
  }

  secret {
    name  = "provider-rate-limit-redis-url"
    value = var.provider_rate_limit_redis_url
  }

  secret {
    name  = "azure-di-key"
    value = azurerm_cognitive_account.document_intelligence.primary_access_key
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "api"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = {
          APP_ENV                     = local.common_environment.APP_ENV
          APP_DEBUG                   = local.common_environment.APP_DEBUG
          APP_API_PREFIX              = local.common_environment.APP_API_PREFIX
          LOG_FORMAT                  = local.common_environment.LOG_FORMAT
          WORKFLOW_QUEUE_MODE         = local.common_environment.WORKFLOW_QUEUE_MODE
          DOCUMENT_STORAGE_PROVIDER   = local.common_environment.DOCUMENT_STORAGE_PROVIDER
          AZURE_STORAGE_CONTAINER     = local.common_environment.AZURE_STORAGE_CONTAINER
          AZURE_STORAGE_BLOB_ENDPOINT = local.common_environment.AZURE_STORAGE_BLOB_ENDPOINT
          OCR_PROVIDER                = local.common_environment.OCR_PROVIDER
          AZURE_DI_ENDPOINT           = local.common_environment.AZURE_DI_ENDPOINT
          AZURE_DI_MODEL_ID           = local.common_environment.AZURE_DI_MODEL_ID
          CORS_ORIGINS                = jsonencode([var.frontend_origin])
        }

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = {
          DATABASE_URL                  = "database-url"
          CELERY_BROKER_URL             = "celery-broker-url"
          CELERY_RESULT_BACKEND         = "celery-result-backend-url"
          PROVIDER_RATE_LIMIT_REDIS_URL = "provider-rate-limit-redis-url"
          AZURE_DI_KEY                  = "azure-di-key"
        }

        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.container_image != null && var.database_url != null && var.celery_broker_url != null && var.celery_result_backend_url != null && var.provider_rate_limit_redis_url != null
      error_message = "Runtime apply needs container_image plus the Neon and Upstash secret variables."
    }

    # GitHub Actions owns image rollout after this initial infrastructure apply.
    ignore_changes = [template[0].container[0].image]
  }
}

resource "azurerm_container_app" "worker" {
  count = var.enable_container_apps ? 1 : 0

  name                         = "ca-${var.project}-worker-${var.environment}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.runtime.id
  }

  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "celery-broker-url"
    value = var.celery_broker_url
  }
  secret {
    name  = "celery-result-backend-url"
    value = var.celery_result_backend_url
  }
  secret {
    name  = "provider-rate-limit-redis-url"
    value = var.provider_rate_limit_redis_url
  }
  secret {
    name  = "azure-di-key"
    value = azurerm_cognitive_account.document_intelligence.primary_access_key
  }

  template {
    min_replicas = var.worker_min_replicas
    max_replicas = var.worker_max_replicas

    container {
      name    = "worker"
      image   = var.container_image
      cpu     = 1.0
      memory  = "2Gi"
      command = ["celery"]
      args    = ["-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2", "--queues=document-processing-high,document-processing-medium,document-processing-low"]

      dynamic "env" {
        for_each = merge(local.common_environment, {
          AZURE_DI_ENDPOINT = local.common_environment.AZURE_DI_ENDPOINT
        })

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = {
          DATABASE_URL                  = "database-url"
          CELERY_BROKER_URL             = "celery-broker-url"
          CELERY_RESULT_BACKEND         = "celery-result-backend-url"
          PROVIDER_RATE_LIMIT_REDIS_URL = "provider-rate-limit-redis-url"
          AZURE_DI_KEY                  = "azure-di-key"
        }

        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.container_image != null && var.database_url != null && var.celery_broker_url != null && var.celery_result_backend_url != null && var.provider_rate_limit_redis_url != null
      error_message = "Runtime apply needs container_image plus the Neon and Upstash secret variables."
    }
    ignore_changes = [template[0].container[0].image]
  }
}

resource "azurerm_container_app" "dispatcher" {
  count = var.enable_container_apps ? 1 : 0

  name                         = "ca-${var.project}-dispatcher-${var.environment}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.runtime.id
  }

  secret {
    name  = "database-url"
    value = var.database_url
  }
  secret {
    name  = "celery-broker-url"
    value = var.celery_broker_url
  }
  secret {
    name  = "celery-result-backend-url"
    value = var.celery_result_backend_url
  }

  template {
    min_replicas = var.dispatcher_min_replicas
    max_replicas = var.dispatcher_max_replicas

    container {
      name    = "dispatcher"
      image   = var.container_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python"]
      args    = ["-m", "app.workers.outbox_dispatcher"]

      dynamic "env" {
        for_each = {
          APP_ENV                      = local.common_environment.APP_ENV
          APP_DEBUG                    = local.common_environment.APP_DEBUG
          LOG_FORMAT                   = local.common_environment.LOG_FORMAT
          WORKFLOW_QUEUE_MODE          = local.common_environment.WORKFLOW_QUEUE_MODE
          OUTBOX_DISPATCHER_ENABLED    = "true"
          OUTBOX_POLL_INTERVAL_SECONDS = local.common_environment.OUTBOX_POLL_INTERVAL_SECONDS
          OUTBOX_BATCH_SIZE            = local.common_environment.OUTBOX_BATCH_SIZE
          OUTBOX_RETRY_BACKOFF_SECONDS = local.common_environment.OUTBOX_RETRY_BACKOFF_SECONDS
        }

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = {
          DATABASE_URL          = "database-url"
          CELERY_BROKER_URL     = "celery-broker-url"
          CELERY_RESULT_BACKEND = "celery-result-backend-url"
        }

        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.container_image != null && var.database_url != null && var.celery_broker_url != null && var.celery_result_backend_url != null
      error_message = "Runtime apply needs container_image plus the Neon and Upstash secret variables."
    }
    ignore_changes = [template[0].container[0].image]
  }
}
