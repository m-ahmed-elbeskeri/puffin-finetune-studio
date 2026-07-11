output "repository_id" {
  value = google_artifact_registry_repository.puffin.repository_id
}

output "repository_uri" {
  value = "${google_artifact_registry_repository.puffin.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.puffin.repository_id}"
}
