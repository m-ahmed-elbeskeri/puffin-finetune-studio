variable "project_id" {
  type        = string
  description = "GCP project ID hosting puffin resources."
}

variable "region" {
  type        = string
  description = "Default GCP region for regional resources."
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "dev | staging | prod"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}

variable "extra_labels" {
  type        = map(string)
  description = "Additional labels applied to every resource."
  default     = {}
}

variable "notification_channels" {
  type        = list(string)
  description = "Cloud Monitoring notification channel IDs (e.g. PagerDuty, email)."
  default     = []
}
