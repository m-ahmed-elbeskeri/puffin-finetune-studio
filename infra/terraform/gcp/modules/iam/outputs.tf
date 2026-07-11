output "training_sa_email" {
  value = google_service_account.training.email
}

output "serving_sa_email" {
  value = google_service_account.serving.email
}
