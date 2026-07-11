output "raw_bucket_name" {
  value = google_storage_bucket.raw.name
}

output "processed_bucket_name" {
  value = google_storage_bucket.processed.name
}

output "artifact_bucket_name" {
  value = google_storage_bucket.artifacts.name
}
