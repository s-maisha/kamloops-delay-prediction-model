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
