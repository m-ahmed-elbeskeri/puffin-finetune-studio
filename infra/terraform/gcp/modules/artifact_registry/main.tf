terraform {
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.0, < 7.0" }
  }
}

resource "google_artifact_registry_repository" "puffin" {
  project       = var.project_id
  location      = var.region
  repository_id = "puffin-${var.environment}"
  description   = "puffin-finetune-studio container images (${var.environment})"
  format        = "DOCKER"
  labels        = var.labels

  cleanup_policies {
    id     = "keep-30-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 30
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state = "UNTAGGED"
      older_than = "604800s"
    }
  }
}
