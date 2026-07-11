###############################################################################
# puffin-finetune-studio — GCP root module
#
# Provisions: project APIs, regional GCS buckets (raw/processed/artifacts),
# Artifact Registry, Vertex AI training/serving service accounts, monitoring
# notification channel, and a starter alert policy on inference latency.
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  base_labels = merge(
    {
      app         = "puffin"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.extra_labels,
  )
}

# --- APIs ---
resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# --- Storage ---
module "storage" {
  source      = "./modules/storage"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  labels      = local.base_labels
  depends_on  = [google_project_service.apis]
}

# --- Container registry ---
module "artifact_registry" {
  source      = "./modules/artifact_registry"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  labels      = local.base_labels
  depends_on  = [google_project_service.apis]
}

# --- IAM (training + serving service accounts) ---
module "iam" {
  source                       = "./modules/iam"
  project_id                   = var.project_id
  environment                  = var.environment
  raw_bucket                   = module.storage.raw_bucket_name
  processed_bucket             = module.storage.processed_bucket_name
  artifact_bucket              = module.storage.artifact_bucket_name
  artifact_registry_repository = module.artifact_registry.repository_id
  depends_on                   = [google_project_service.apis]
}

# --- Monitoring ---
module "monitoring" {
  source                = "./modules/monitoring"
  project_id            = var.project_id
  environment           = var.environment
  notification_channels = var.notification_channels
  depends_on            = [google_project_service.apis]
}
