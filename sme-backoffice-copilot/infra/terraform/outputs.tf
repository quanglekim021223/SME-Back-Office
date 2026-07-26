output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "storage_account_name" {
  value = azurerm_storage_account.documents.name
}

output "storage_blob_endpoint" {
  value = azurerm_storage_account.documents.primary_blob_endpoint
}

output "document_intelligence_endpoint" {
  value = azurerm_cognitive_account.document_intelligence.endpoint
}

output "runtime_identity_client_id" {
  value = azurerm_user_assigned_identity.runtime.client_id
}

output "github_actions_client_id" {
  description = "Set this as the AZURE_CLIENT_ID GitHub Actions secret after recreation."
  value       = azurerm_user_assigned_identity.github_deployment.client_id
}

output "api_url" {
  value = try("https://${azurerm_container_app.api[0].ingress[0].fqdn}", null)
}
