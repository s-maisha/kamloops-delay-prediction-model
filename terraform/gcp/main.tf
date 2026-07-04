terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP Region"
}

variable "bucket_name" {
  type        = string
  description = "Globally unique name for the GCS bucket to store GTFS data"
}

# Bucket for GTFS Realtime data
resource "google_storage_bucket" "gtfs_data" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = false

  uniform_bucket_level_access = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 365 # Keep data for 1 year
    }
  }
}

# Grant public read access to the GCS bucket so collaborators can sync anonymously
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.gtfs_data.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# Bucket for Cloud Function source archives
resource "google_storage_bucket" "function_source" {
  name          = "${var.bucket_name}-function-source"
  location      = var.region
  force_destroy = true
  uniform_bucket_level_access = true
}

# Archive function code
data "archive_file" "function_zip" {
  type        = "zip"
  source_dir  = "${path.module}/function"
  output_path = "${path.module}/function.zip"
}

# Upload zipped code to bucket
resource "google_storage_bucket_object" "function_zip_object" {
  name   = "function-${data.archive_file.function_zip.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.function_zip.output_path
}

# Cloud Function (Gen 2)
resource "google_cloudfunctions2_function" "gtfs_collector" {
  name        = "gtfs-realtime-collector"
  location    = var.region
  description = "Function to collect GTFS Realtime data from Kamloops API"

  build_config {
    runtime     = "python310"
    entry_point = "collect_feed"
    
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_zip_object.name
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256M"
    timeout_seconds    = 60
    
    environment_variables = {
      BUCKET_NAME = google_storage_bucket.gtfs_data.name
    }
  }

  depends_on = [
    google_project_iam_member.default_compute_builder,
    google_project_iam_member.default_compute_storage_viewer,
    google_project_iam_member.default_compute_artifact_writer,
    google_project_iam_member.default_compute_logging_writer,
  ]
}

# Create Service Account for Cloud Scheduler
resource "google_service_account" "scheduler_sa" {
  account_id   = "gtfs-scheduler-sa"
  display_name = "GTFS Scheduler Service Account"
}

# Grant Scheduler service account permission to call the function
resource "google_cloudfunctions2_function_iam_member" "scheduler_invoker" {
  project        = google_cloudfunctions2_function.gtfs_collector.project
  location       = google_cloudfunctions2_function.gtfs_collector.location
  cloud_function = google_cloudfunctions2_function.gtfs_collector.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

# Grant Cloud Run Invoker role since CF Gen2 runs on Cloud Run
resource "google_cloud_run_service_iam_member" "scheduler_run_invoker" {
  project  = google_cloudfunctions2_function.gtfs_collector.project
  location = google_cloudfunctions2_function.gtfs_collector.location
  service  = google_cloudfunctions2_function.gtfs_collector.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

# Cloud Scheduler job to trigger function every minute
resource "google_cloud_scheduler_job" "cron" {
  name             = "gtfs-collector-trigger"
  description      = "Trigger GTFS Realtime collector function every minute"
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "60s"

  http_target {
    http_method = "GET"
    uri         = google_cloudfunctions2_function.gtfs_collector.service_config[0].uri
    
    oidc_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }
}

# -----------------------------------------------------------------------------
# IAM Permissions for Default Compute Service Account (Build & Runtime)
# -----------------------------------------------------------------------------

# Retrieve project metadata to get the project number dynamically
data "google_project" "project" {}

# Grant the Cloud Build Service Account role to the default Compute Engine service account.
# This resolves the "missing permission on the build service account" error when deploying
# Gen 2 Cloud Functions in organizations with strict default service account policies.
resource "google_project_iam_member" "default_compute_builder" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Grant Storage Object Viewer to the default Compute Engine service account
# to read the zipped Cloud Function code during building.
resource "google_project_iam_member" "default_compute_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Grant Artifact Registry Writer to the default Compute Engine service account
# to push the built container image to Artifact Registry.
resource "google_project_iam_member" "default_compute_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Grant Logs Writer to the default Compute Engine service account
# so the build and the function runtime can write logs to Cloud Logging.
resource "google_project_iam_member" "default_compute_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}

# Grant Storage Object Creator role on the GTFS data bucket to the default Compute Engine
# service account, allowing the Cloud Function to upload collected feed data at runtime.
resource "google_storage_bucket_iam_member" "default_compute_gcs_writer" {
  bucket = google_storage_bucket.gtfs_data.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}
