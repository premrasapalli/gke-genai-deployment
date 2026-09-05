resource "google_service_account" "gke" {
  account_id   = "genai-gke"
  display_name = "GenAI GKE cluster"
}

data "google_container_engine_versions" "default" {
  location = var.region
  project  = var.project_id
}

resource "google_container_cluster" "genai" {
  name                     = "genai-cluster"
  location                 = var.region
  remove_default_node_pool = true
  initial_node_count       = 1
  networking_mode          = "VPC_NATIVE"

  deletion_protection = false
  # Enable Autopilot or Standard? We use Standard with a GPU-ready node pool.

  node_config {
    service_account = google_service_account.gke.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
  }
}

resource "google_container_node_pool" "cpu" {
  name       = "cpu-pool"
  cluster    = google_container_cluster.genai.id
  node_count = 1

  node_config {
    machine_type    = "e2-standard-8"
    service_account = google_service_account.gke.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
  }
}

resource "google_container_node_pool" "gpu" {
  name       = "gpu-pool"
  cluster    = google_container_cluster.genai.id
  node_count = 1

  node_config {
    machine_type = "g2-standard-12" # 1 x NVIDIA L4 GPU; large GPU models need more
    service_account = google_service_account.gke.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
    guest_accelerator {
      type  = "nvidia-l4"
      count = 1
    }
  }
}

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "genai"
  format        = "DOCKER"
  description   = "GenAI serving, RAG and gateway images"
}