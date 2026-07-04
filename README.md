# Kamloops Delay Prediction Model - Data Collection

This project provides tools for importing static GTFS data and collecting GTFS Realtime feeds for BC Transit's Kamloops transit system. It supports both local SQLite ingestion (for development and prototyping) and cloud-based collection on Google Cloud Platform (GCP) or Amazon Web Services (AWS) using Terraform.

## Project Structure

*   `static-data/`: Contains static GTFS text files (routes, stops, trips, etc.).
*   [import_static_data.py](file:///home/marvellous/Projects/python/kamloops-delay-prediction-model/import_static_data.py): Reads static GTFS data and populates tables in a local SQLite database (`gtfs.db`).
*   [collect_realtime_data.py](file:///home/marvellous/Projects/python/kamloops-delay-prediction-model/collect_realtime_data.py): Fetches real-time GTFS feeds (Trip Updates and Vehicle Positions) and saves them into the local SQLite database.
*   `terraform/`: Contains infrastructure-as-code files to set up scheduled cloud-based collection pipelines.
    *   `gcp/`: Google Cloud Platform deployment using Cloud Functions (Gen 2), Cloud Scheduler, and Cloud Storage.
    *   `aws/`: Amazon Web Services deployment using Lambda, EventBridge, and S3.

---

## Local Setup & Collection

### 1. Requirements
Ensure you have Python 3.10+ installed. Install the Python dependencies:
```bash
pip install -r terraform/gcp/function/requirements.txt google-transit
```

### 2. Import Static Data
Populate the SQLite database with the static GTFS schedule:
```bash
python import_static_data.py
```
This parses the `.txt` files in `static-data/` and builds the database schema and indexes.

### 3. Run Real-time Collector Locally
You can run the collector in a loop to poll and save updates every minute:
```bash
python collect_realtime_data.py
```
Or run it once:
```bash
python collect_realtime_data.py --once
```

---

## GCP Deployment (Terraform)

The GCP architecture schedules a **Cloud Function (Gen 2)** to run every minute via **Cloud Scheduler**, downloading the GTFS-RT feed and storing the raw `.pb` files in a **Google Cloud Storage (GCS)** bucket.

### Architecture Flow
```
[Cloud Scheduler] --(HTTPS GET)--> [Cloud Function] ----> [Fetches feeds from API]
                                            |
                                            v (Writes raw Protobufs)
                                    [GCS Data Bucket]
                               (organized by type & date)
```

### 1. Installing CLI Tools (Fedora 44)

If you need to install the CLI tools, run the following:

#### Install Terraform
```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager addrepo --from-repofile=https://rpm.releases.hashicorp.com/fedora/hashicorp.repo
sudo dnf install -y terraform
```

#### Install Google Cloud SDK
```bash
# Add the Google Cloud SDK repo
sudo tee /etc/yum.repos.d/google-cloud-sdk.repo <<EOF
[google-cloud-sdk]
name=Google Cloud SDK
baseurl=https://packages.cloud.google.com/yum/repos/cloud-sdk-el9-x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
EOF

# Install the CLI
sudo dnf install -y google-cloud-cli
```

### 2. Authenticating with GCP

1.  Log in to your Google Account:
    ```bash
    gcloud auth login
    ```
2.  Configure your active project:
    ```bash
    gcloud config set project your-gcp-project-id
    ```
3.  Set application default credentials for Terraform:
    ```bash
    gcloud auth application-default login
    ```

### 3. Deploying using Terraform

1.  Navigate to the GCP Terraform directory:
    ```bash
    cd terraform/gcp
    ```
2.  Copy the example variables file:
    ```bash
    cp terraform.tfvars.example terraform.tfvars
    ```
3.  Open `terraform.tfvars` and update the values:
    *   `project_id`: Your Google Cloud Project ID.
    *   `bucket_name`: A globally unique name for your GCS bucket.
    *   `region`: The region to deploy to (default: `us-central1`).
4.  Initialize Terraform:
    ```bash
    terraform init
    ```
5.  View the planned changes:
    ```bash
    terraform plan
    ```
6.  Apply the changes to deploy the resources:
    ```bash
    terraform apply
    ```

### 4. Enable Required GCP APIs
Before running `terraform apply`, ensure the following APIs are enabled in your Google Cloud Console or via gcloud:
```bash
gcloud services enable \
    cloudresourcemanager.googleapis.com \
    iam.googleapis.com \
    cloudfunctions.googleapis.com \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    cloudscheduler.googleapis.com
```

### 5. Syncing Cloud Data to Local SQLite Database

If you use the GCP Serverless pipeline, your raw realtime data is saved in a Google Cloud Storage (GCS) bucket. To bring this data down locally for modeling:

1.  Make sure you have configured GCP credentials on your local machine (`gcloud auth application-default login`).
2.  Install the required dependencies:
    ```bash
    pip install google-cloud-storage google-transit
    ```
3.  Run [sync_gcs_to_sqlite.py](file:///home/marvellous/Projects/python/kamloops-delay-prediction-model/sync_gcs_to_sqlite.py) with the GCS bucket name to download and parse all collected `.pb` files directly into your local `gtfs.db`:
    ```bash
    python sync_gcs_to_sqlite.py <your-gcs-bucket-name>
    ```
    This script parses the feeds and uses `INSERT OR IGNORE` to insert records, safely ignoring any duplicates you already have in the database.

