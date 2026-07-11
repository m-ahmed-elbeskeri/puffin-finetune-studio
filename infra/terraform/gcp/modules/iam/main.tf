terraform {
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.0, < 7.0" }
  }
}

# Training service account: read raw + write processed/artifacts.
resource "google_service_account" "training" {
  account_id   = "puffin-${var.environment}-train"
  display_name = "puffin training (${var.environment})"
}

resource "google_service_account" "serving" {
  account_id   = "puffin-${var.environment}-serve"
  display_name = "puffin serving (${var.environment})"
}

resource "google_storage_bucket_iam_member" "train_raw_reader" {
  bucket = var.raw_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.training.email}"
}

resource "google_storage_bucket_iam_member" "train_processed_writer" {
  bucket = var.processed_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.training.email}"
}

resource "google_storage_bucket_iam_member" "train_artifacts_writer" {
  bucket = var.artifact_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.training.email}"
}

resource "google_storage_bucket_iam_member" "serve_artifacts_reader" {
  bucket = var.artifact_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.serving.email}"
}

resource "google_project_iam_member" "training_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.training.email}"
}

resource "google_project_iam_member" "serving_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.serving.email}"
}

resource "google_artifact_registry_repository_iam_member" "training_image_pull" {
  project    = var.project_id
  location   = "us-central1"
  repository = var.artifact_registry_repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.training.email}"
}

resource "google_artifact_registry_repository_iam_member" "serving_image_pull" {
  project    = var.project_id
  location   = "us-central1"
  repository = var.artifact_registry_repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.serving.email}"
}
