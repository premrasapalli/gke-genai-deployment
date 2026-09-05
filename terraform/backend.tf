terraform {
  backend "gcs" {
    bucket = "genai-terraform-state"
    prefix = "terraform/state"
  }
}