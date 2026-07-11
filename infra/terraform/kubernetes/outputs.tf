output "namespace" {
  value = kubernetes_namespace_v1.puffin.metadata[0].name
}

output "service_url" {
  value = "http://${kubernetes_service_v1.serve.metadata[0].name}.${kubernetes_namespace_v1.puffin.metadata[0].name}.svc.cluster.local"
}
