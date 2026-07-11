###############################################################################
# puffin-finetune-studio — Kubernetes deployment (vLLM serving).
#
# Cluster-agnostic: works on GKE / EKS / AKS / vanilla k8s.
# Provisions: namespace, ServiceAccount, Deployment, Service, HPA, optional
# ServiceMonitor for Prometheus.
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.27"
    }
  }
}

provider "kubernetes" {}

locals {
  app_name = "puffin-${var.environment}"
}

resource "kubernetes_namespace_v1" "puffin" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
      "puffin.environment"           = var.environment
    }
  }
}

resource "kubernetes_service_account_v1" "puffin" {
  metadata {
    name      = local.app_name
    namespace = kubernetes_namespace_v1.puffin.metadata[0].name
  }
  automount_service_account_token = true
}

resource "kubernetes_deployment_v1" "serve" {
  metadata {
    name      = local.app_name
    namespace = kubernetes_namespace_v1.puffin.metadata[0].name
    labels = {
      app                  = local.app_name
      "puffin.environment" = var.environment
    }
  }
  spec {
    replicas = var.replicas
    selector { match_labels = { app = local.app_name } }
    template {
      metadata {
        labels = {
          app                  = local.app_name
          "puffin.environment" = var.environment
        }
        annotations = {
          "prometheus.io/scrape" = "true"
          "prometheus.io/port"   = "8080"
          "prometheus.io/path"   = "/metrics"
        }
      }
      spec {
        service_account_name = kubernetes_service_account_v1.puffin.metadata[0].name
        container {
          name  = "serve"
          image = var.serving_image
          args  = ["--config", "/app/configs/deploy.yaml", "--host", "0.0.0.0", "--port", "8080"]

          dynamic "env" {
            for_each = var.env_vars
            content {
              name  = env.key
              value = env.value
            }
          }

          port {
            container_port = 8080
            name           = "http"
          }

          resources {
            requests = {
              cpu    = var.cpu_request
              memory = var.memory_request
            }
            limits = merge(
              {
                cpu    = var.cpu_limit
                memory = var.memory_limit
              },
              var.gpu_count > 0 ? { "nvidia.com/gpu" = tostring(var.gpu_count) } : {},
            )
          }

          readiness_probe {
            http_get {
              path = "/ready"
              port = 8080
            }
            initial_delay_seconds = 30
            period_seconds        = 5
          }

          liveness_probe {
            http_get {
              path = "/health"
              port = 8080
            }
            initial_delay_seconds = 60
            period_seconds        = 10
          }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "serve" {
  metadata {
    name      = local.app_name
    namespace = kubernetes_namespace_v1.puffin.metadata[0].name
  }
  spec {
    selector = { app = local.app_name }
    port {
      name        = "http"
      port        = 80
      target_port = 8080
    }
    type = "ClusterIP"
  }
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "serve" {
  metadata {
    name      = local.app_name
    namespace = kubernetes_namespace_v1.puffin.metadata[0].name
  }
  spec {
    scale_target_ref {
      api_version = "apps/v1"
      kind        = "Deployment"
      name        = kubernetes_deployment_v1.serve.metadata[0].name
    }
    min_replicas = var.replicas
    max_replicas = var.max_replicas

    metric {
      type = "Resource"
      resource {
        name = "cpu"
        target {
          type                = "Utilization"
          average_utilization = 70
        }
      }
    }
  }
}
