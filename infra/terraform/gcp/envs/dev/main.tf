variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

module "puffin" {
  source = "../.."

  project_id  = var.project_id
  region      = var.region
  environment = "dev"
  extra_labels = {
    cost_center = "research"
  }
}
