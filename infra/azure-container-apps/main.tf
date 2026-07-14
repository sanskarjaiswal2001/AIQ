terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "random_password" "admin_key" {
  length  = 40
  special = false
}

locals {
  name_prefix      = "${var.project}-${var.environment}"
  resource_group   = "${local.name_prefix}-rg"
  acr_name         = replace("${var.project}${var.environment}${random_string.suffix.result}", "-", "")
  storage_name     = substr(replace("${var.project}${var.environment}${random_string.suffix.result}data", "-", ""), 0, 24)
  aiq_image        = "${azurerm_container_registry.acr.login_server}/aiq:${var.image_tag}"
  aiq_admin_key    = coalesce(var.aiq_admin_key, random_password.admin_key.result)
}

resource "azurerm_resource_group" "main" {
  name     = local.resource_group
  location = var.location
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name_prefix}-logs"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "acr" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
}

resource "azurerm_storage_account" "data" {
  name                     = local.storage_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_share" "data" {
  name               = "aiq-data"
  storage_account_id = azurerm_storage_account.data.id
  quota              = 10
}

resource "azurerm_container_app_environment_storage" "data" {
  name                         = "aiq-data"
  container_app_environment_id = azurerm_container_app_environment.main.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.data.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${local.name_prefix}-env"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

resource "azurerm_container_app" "aiq" {
  name                         = "${local.name_prefix}-mothership"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  secret {
    name  = "aiq-admin-key"
    value = local.aiq_admin_key
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.acr.admin_password
  }

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "acr-password"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1 # ponytail: SQLite app, switch to Postgres before scaling replicas.

    container {
      name   = "aiq"
      image  = var.initial_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "AIQ_ADMIN_KEY"
        secret_name = "aiq-admin-key"
      }

      env {
        name  = "DB_PATH"
        value = "/data/aiq.db"
      }

      volume_mounts {
        name = "aiq-data"
        path = "/data"
      }
    }

    volume {
      name         = "aiq-data"
      storage_name = azurerm_container_app_environment_storage.data.name
      storage_type = "AzureFile"
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}
