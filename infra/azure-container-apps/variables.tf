variable "project" {
  description = "Short project name used in Azure resource names."
  type        = string
  default     = "aiq"
}

variable "environment" {
  description = "Environment name, for example prod or demo."
  type        = string
  default     = "prod"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "centralindia"
}

variable "image_tag" {
  description = "AIQ image tag to build/push to ACR."
  type        = string
  default     = "latest"
}

variable "initial_image" {
  description = "Bootstrap image for first terraform apply. The README updates the app to the ACR AIQ image after az acr build."
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "aiq_admin_key" {
  description = "Optional admin key. If null, Terraform generates one and stores it in Container Apps secrets."
  type        = string
  default     = null
  sensitive   = true
}
