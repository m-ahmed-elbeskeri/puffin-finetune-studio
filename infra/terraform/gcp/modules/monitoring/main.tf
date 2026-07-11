terraform {
  required_providers {
    google = { source = "hashicorp/google", version = ">= 5.0, < 7.0" }
  }
}

resource "google_logging_metric" "inference_errors" {
  name        = "puffin-${var.environment}-inference-errors"
  description = "Count of puffin inference errors logged at ERROR or above."

  filter = <<-EOT
    resource.type="generic_task"
    severity>=ERROR
    jsonPayload.logger=~"^llmops\\."
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    display_name = "Puffin inference errors (${var.environment})"
  }
}

resource "google_monitoring_alert_policy" "high_p95_latency" {
  count        = length(var.notification_channels) > 0 ? 1 : 0
  display_name = "puffin-${var.environment}: high p95 latency"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "p95 inference latency > 3s for 5m"
    condition_threshold {
      filter          = "metric.type=\"prometheus.googleapis.com/puffin_inference_latency_seconds/histogram\" resource.type=\"prometheus_target\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 3.0
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
    }
  }

  notification_channels = var.notification_channels
}
