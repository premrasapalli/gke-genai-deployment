output "cluster_name" {
  value = google_container_cluster.genai.name
}

output "cluster_endpoint" {
  value = google_container_cluster.genai.endpoint
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/genai"
}

output "gpu_pool_id" {
  value = google_container_node_pool.gpu.name
}