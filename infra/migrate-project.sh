#!/usr/bin/env bash
# migrate-project.sh — Deploy Catalog Intelligence Engine to a GCP project
#
# Usage:
#   export DB_PASSWORD="your-db-password"
#   export ALGOLIA_APP_ID="..." ALGOLIA_API_KEY="..." ALGOLIA_INDEX_NAME="..."
#   ./infra/migrate-project.sh <TARGET_PROJECT_ID> [--copy-data]
#
# Options:
#   --copy-data   Export data from SOURCE_PROJECT and import into target
#
# Environment variables:
#   DB_PASSWORD          (required) Password for the Cloud SQL 'catalog' user
#   ALGOLIA_APP_ID       (required) Shared Algolia application ID
#   ALGOLIA_API_KEY      (required) Shared Algolia API key
#   ALGOLIA_INDEX_NAME   (required) Shared Algolia index name
#   SOURCE_PROJECT       (optional) Source project for data copy (default: catalog-engine-489719)
#   REGION               (optional) GCP region (default: us-central1)
#   SQL_TIER             (optional) Cloud SQL tier (default: db-f1-micro)

set -euo pipefail

# --- Args ---
TARGET_PROJECT="${1:?Usage: $0 <TARGET_PROJECT_ID> [--copy-data]}"
COPY_DATA=false
if [[ "${2:-}" == "--copy-data" ]]; then
  COPY_DATA=true
fi

# --- Config ---
SOURCE_PROJECT="${SOURCE_PROJECT:-catalog-engine-489719}"
REGION="${REGION:-us-central1}"
SQL_TIER="${SQL_TIER:-db-f1-micro}"
SQL_INSTANCE="catalog-db"
DB_NAME="catalog_engine"
DB_USER="catalog"
BUCKET="${TARGET_PROJECT}-catalog-exports"
GITHUB_OWNER="Wunderbot-Git"
GITHUB_REPO="catalog-engine"

# --- Validate env vars ---
: "${DB_PASSWORD:?Set DB_PASSWORD env var}"
ALGOLIA_APP_ID="${ALGOLIA_APP_ID:-}"
ALGOLIA_API_KEY="${ALGOLIA_API_KEY:-}"
ALGOLIA_INDEX_NAME="${ALGOLIA_INDEX_NAME:-}"
if [[ -z "${ALGOLIA_APP_ID}" ]]; then
  echo "Note: ALGOLIA_* env vars not set — Algolia secrets will be created with empty values."
fi

echo "============================================"
echo "Migrating to project: ${TARGET_PROJECT}"
echo "Region: ${REGION}"
echo "Cloud SQL: ${SQL_INSTANCE} (${SQL_TIER})"
echo "Bucket: gs://${BUCKET}"
if $COPY_DATA; then
  echo "Data copy: from ${SOURCE_PROJECT}"
fi
echo "============================================"
echo ""

# --- Step 1: Set project & enable APIs ---
echo ">>> Step 1: Setting project and enabling APIs..."
gcloud config set project "${TARGET_PROJECT}"

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  containerregistry.googleapis.com \
  iap.googleapis.com \
  cloudresourcemanager.googleapis.com

echo "    APIs enabled."

# --- Step 2: Create Cloud SQL instance + database ---
echo ">>> Step 2: Creating Cloud SQL instance..."

if gcloud sql instances describe "${SQL_INSTANCE}" --project="${TARGET_PROJECT}" &>/dev/null; then
  echo "    Cloud SQL instance '${SQL_INSTANCE}' already exists, skipping creation."
else
  gcloud sql instances create "${SQL_INSTANCE}" \
    --database-version=POSTGRES_15 \
    --tier="${SQL_TIER}" \
    --region="${REGION}" \
    --root-password="${DB_PASSWORD}"
  echo "    Instance created."
fi

# Create database (ignore if exists)
gcloud sql databases create "${DB_NAME}" --instance="${SQL_INSTANCE}" 2>/dev/null || \
  echo "    Database '${DB_NAME}' already exists."

# Create user (ignore if exists)
gcloud sql users create "${DB_USER}" \
  --instance="${SQL_INSTANCE}" \
  --password="${DB_PASSWORD}" 2>/dev/null || \
  echo "    User '${DB_USER}' already exists."

echo "    Cloud SQL ready."

# --- Step 3: Create Cloud Storage bucket ---
echo ">>> Step 3: Creating Cloud Storage bucket..."
gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" 2>/dev/null || \
  echo "    Bucket 'gs://${BUCKET}' already exists."

# --- Step 4: Create secrets ---
echo ">>> Step 4: Creating Secret Manager secrets..."

create_secret() {
  local name="$1"
  local value="$2"
  # Use placeholder if value is empty (Cloud Run requires a version to exist)
  if [[ -z "${value}" ]]; then
    value="placeholder"
  fi
  if gcloud secrets describe "${name}" --project="${TARGET_PROJECT}" &>/dev/null; then
    echo "    Secret '${name}' exists, adding new version..."
    echo -n "${value}" | gcloud secrets versions add "${name}" --data-file=-
  else
    echo -n "${value}" | gcloud secrets create "${name}" --data-file=-
  fi
}

DB_URL="postgresql://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${TARGET_PROJECT}:${REGION}:${SQL_INSTANCE}"

create_secret "catalog-database-url" "${DB_URL}"
create_secret "catalog-export-bucket" "${BUCKET}"
create_secret "catalog-iap-audience" "disabled"
create_secret "catalog-algolia-app-id" "${ALGOLIA_APP_ID}"
create_secret "catalog-algolia-api-key" "${ALGOLIA_API_KEY}"
create_secret "catalog-algolia-index-name" "${ALGOLIA_INDEX_NAME}"

echo "    Secrets configured."

# --- Step 5: Grant IAM roles ---
echo ">>> Step 5: Granting IAM roles..."

PROJECT_NUMBER=$(gcloud projects describe "${TARGET_PROJECT}" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

# Roles for default compute SA (used by Cloud Run)
for role in \
  roles/secretmanager.secretAccessor \
  roles/cloudsql.client \
  roles/aiplatform.user \
  roles/storage.admin; do
  gcloud projects add-iam-policy-binding "${TARGET_PROJECT}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="${role}" \
    --quiet
done

# Roles for Cloud Build SA
for role in \
  roles/run.admin \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${TARGET_PROJECT}" \
    --member="serviceAccount:${CLOUDBUILD_SA}" \
    --role="${role}" \
    --quiet
done

echo "    IAM roles granted."

# --- Step 6: Data migration (optional) ---
if $COPY_DATA; then
  echo ">>> Step 6: Copying data from ${SOURCE_PROJECT}..."

  DUMP_PATH="gs://${SOURCE_PROJECT}-catalog-exports/migration-dump.sql"

  # Grant target project's Cloud SQL SA read access to source bucket
  SOURCE_SA=$(gcloud sql instances describe "${SQL_INSTANCE}" \
    --project="${SOURCE_PROJECT}" --format='value(serviceAccountEmailAddress)' 2>/dev/null || true)
  TARGET_SQL_SA=$(gcloud sql instances describe "${SQL_INSTANCE}" \
    --project="${TARGET_PROJECT}" --format='value(serviceAccountEmailAddress)')

  echo "    Exporting from source..."
  gcloud sql export sql "${SQL_INSTANCE}" "${DUMP_PATH}" \
    --database="${DB_NAME}" \
    --project="${SOURCE_PROJECT}" 2>/dev/null || \
    echo "    Warning: Export failed or dump already exists. Trying import anyway..."

  # Grant target SQL SA access to source bucket
  gcloud storage buckets add-iam-policy-binding "gs://${SOURCE_PROJECT}-catalog-exports" \
    --member="serviceAccount:${TARGET_SQL_SA}" \
    --role="roles/storage.objectViewer" 2>/dev/null || true

  echo "    Importing into target..."
  gcloud sql import sql "${SQL_INSTANCE}" "${DUMP_PATH}" \
    --database="${DB_NAME}" \
    --project="${TARGET_PROJECT}" || \
    echo "    Warning: Import failed. You may need to run Alembic migrations manually."

  echo "    Data migration complete."
else
  echo ">>> Step 6: Skipping data copy (no --copy-data flag)."
  echo "    Alembic will create the schema on first deploy."
fi

# --- Step 7: Set up Cloud Build trigger ---
echo ">>> Step 7: Setting up Cloud Build trigger..."

# Check if trigger already exists
EXISTING=$(gcloud builds triggers list --project="${TARGET_PROJECT}" \
  --filter="name=catalog-engine-main" --format='value(name)' 2>/dev/null || true)

if [[ -n "${EXISTING}" ]]; then
  echo "    Build trigger already exists, skipping."
else
  echo "    Note: GitHub repo connection may need to be set up in the Console first."
  echo "    Visit: https://console.cloud.google.com/cloud-build/triggers?project=${TARGET_PROJECT}"
  gcloud builds triggers create github \
    --name="catalog-engine-main" \
    --repo-name="${GITHUB_REPO}" \
    --repo-owner="${GITHUB_OWNER}" \
    --branch-pattern="^main$" \
    --build-config=cloudbuild.yaml \
    --substitutions="_REGION=${REGION},_CLOUD_SQL_INSTANCE=${TARGET_PROJECT}:${REGION}:${SQL_INSTANCE}" \
    2>/dev/null || \
    echo "    Warning: Trigger creation failed. Set up GitHub connection in Console first."
fi

# --- Step 8: Trigger first deploy ---
echo ">>> Step 8: Triggering first deploy..."
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_CLOUD_SQL_INSTANCE=${TARGET_PROJECT}:${REGION}:${SQL_INSTANCE},_TAG=latest" \
  --project="${TARGET_PROJECT}" || {
    echo "    Deploy failed. Check Cloud Build logs:"
    echo "    https://console.cloud.google.com/cloud-build/builds?project=${TARGET_PROJECT}"
    exit 1
  }

# --- Step 9: Verify ---
echo ""
echo ">>> Step 9: Verifying deployment..."

API_URL=$(gcloud run services describe catalog-api \
  --region="${REGION}" --project="${TARGET_PROJECT}" \
  --format='value(status.url)' 2>/dev/null || echo "")

UI_URL=$(gcloud run services describe catalog-ui \
  --region="${REGION}" --project="${TARGET_PROJECT}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo ""
echo "============================================"
echo "Migration complete for ${TARGET_PROJECT}"
echo "============================================"
echo "API: ${API_URL:-NOT DEPLOYED}"
echo "UI:  ${UI_URL:-NOT DEPLOYED}"
echo ""

if [[ -n "${API_URL}" ]]; then
  echo "Health check:"
  curl -s "${API_URL}/health" || echo "(failed)"
  echo ""
fi

echo ""
echo "Next steps:"
echo "  1. Configure IAP audience if needed"
echo "  2. Seed admin users in the database"
echo "  3. Test: curl ${API_URL:-<API_URL>}/health"
echo "  4. Open: ${UI_URL:-<UI_URL>}"
