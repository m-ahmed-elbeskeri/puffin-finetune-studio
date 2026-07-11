output "raw_bucket" {
  description = "GCS bucket for raw data."
  value       = module.storage.raw_bucket_name
}

output "processed_bucket" {
  description = "GCS bucket for processed data."
  value       = module.storage.processed_bucket_name
}

output "artifact_bucket" {
  description = "GCS bucket for trained model artifacts."
  value       = module.storage.artifact_bucket_name
}

output "artifact_registry_repository" {
  description = "Artifact Registry container repository for puffin images."
  value       = module.artifact_registry.repository_id
}

output "training_service_account" {
  description = "Service account email used by training jobs."
  value       = module.iam.training_sa_email
}

output "serving_service_account" {
  description = "Service account email used by serving endpoints."
  value       = module.iam.serving_sa_email
}
