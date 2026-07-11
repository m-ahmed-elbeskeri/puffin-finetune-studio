###############################################################################
# puffin-finetune-studio — Azure root module
#
# Provisions: Resource Group, Storage Account + containers, ACR,
# Azure ML workspace + Application Insights.
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.100, < 5.0"
    }
  }
}

provider "azurerm" {
  features {}
}

locals {
  base_tags = merge(
    {
      app         = "puffin"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.extra_tags,
  )
  prefix = "puffin${var.environment}"
}

resource "azurerm_resource_group" "puffin" {
  name     = "rg-${local.prefix}"
  location = var.location
  tags     = local.base_tags
}

resource "azurerm_storage_account" "puffin" {
  name                            = local.prefix
  resource_group_name             = azurerm_resource_group.puffin.name
  location                        = azurerm_resource_group.puffin.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  is_hns_enabled                  = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  tags                            = local.base_tags
}

resource "azurerm_storage_container" "raw" {
  name                  = "raw"
  storage_account_name  = azurerm_storage_account.puffin.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "processed" {
  name                  = "processed"
  storage_account_name  = azurerm_storage_account.puffin.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "artifacts" {
  name                  = "artifacts"
  storage_account_name  = azurerm_storage_account.puffin.name
  container_access_type = "private"
}

resource "azurerm_container_registry" "puffin" {
  name                = local.prefix
  resource_group_name = azurerm_resource_group.puffin.name
  location            = azurerm_resource_group.puffin.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = local.base_tags
}

resource "azurerm_log_analytics_workspace" "puffin" {
  name                = "log-${local.prefix}"
  location            = azurerm_resource_group.puffin.location
  resource_group_name = azurerm_resource_group.puffin.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.base_tags
}

resource "azurerm_application_insights" "puffin" {
  name                = "appi-${local.prefix}"
  location            = azurerm_resource_group.puffin.location
  resource_group_name = azurerm_resource_group.puffin.name
  workspace_id        = azurerm_log_analytics_workspace.puffin.id
  application_type    = "other"
  tags                = local.base_tags
}

resource "azurerm_key_vault" "puffin" {
  name                       = "kv-${local.prefix}"
  location                   = azurerm_resource_group.puffin.location
  resource_group_name        = azurerm_resource_group.puffin.name
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = local.base_tags
}

resource "azurerm_machine_learning_workspace" "puffin" {
  name                    = "ml-${local.prefix}"
  location                = azurerm_resource_group.puffin.location
  resource_group_name     = azurerm_resource_group.puffin.name
  application_insights_id = azurerm_application_insights.puffin.id
  key_vault_id            = azurerm_key_vault.puffin.id
  storage_account_id      = azurerm_storage_account.puffin.id
  container_registry_id   = azurerm_container_registry.puffin.id
  identity {
    type = "SystemAssigned"
  }
  tags = local.base_tags
}
