output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "container_app_name" {
  value = azurerm_container_app.aiq.name
}

output "container_app_fqdn" {
  value = azurerm_container_app.aiq.ingress[0].fqdn
}

output "container_app_url" {
  value = "https://${azurerm_container_app.aiq.ingress[0].fqdn}"
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "aiq_image" {
  value = local.aiq_image
}

output "aiq_admin_key" {
  value     = local.aiq_admin_key
  sensitive = true
}
