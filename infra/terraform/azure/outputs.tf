output "resource_group" {
  value = azurerm_resource_group.puffin.name
}

output "storage_account" {
  value = azurerm_storage_account.puffin.name
}

output "container_registry" {
  value = azurerm_container_registry.puffin.login_server
}

output "azureml_workspace" {
  value = azurerm_machine_learning_workspace.puffin.name
}

output "key_vault" {
  value = azurerm_key_vault.puffin.name
}
