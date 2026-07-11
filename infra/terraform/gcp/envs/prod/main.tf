variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "notification_channels" {
  type    = list(string)
  default = []
}

module "puffin" {
  source = "../.."

  project_id            = var.project_id
  region                = var.region
  environment           = "prod"
  notification_channels = var.notification_channels
  extra_labels = {
    cost_center = "core"
    pii         = "yes"
  }
}
