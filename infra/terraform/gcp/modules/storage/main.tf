terraform {
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.0, < 7.0" }
  }
}

locals {
  prefix = "puffin-${var.environment}"
}

resource "google_storage_bucket" "raw" {
  name                        = "${local.prefix}-raw"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"
  labels                      = var.labels

  versioning { enabled = true }

  lifecycle_rule {
    condition { age = 365 }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }
}

resource "google_storage_bucket" "processed" {
  name                        = "${local.prefix}-processed"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"
  labels                      = var.labels

  versioning { enabled = true }
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${local.prefix}-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.environment != "prod"
  labels                      = var.labels

  versioning { enabled = true }

  lifecycle_rule {
    condition { num_newer_versions = 10 }
    action { type = "Delete" }
  }
}
