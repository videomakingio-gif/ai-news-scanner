#!/bin/bash
# ============================================================
# Deploy AI News Scanner to Cloud Run Job + Cloud Scheduler
# ============================================================
# Prerequisites:
#   - gcloud CLI authenticated
#   - GCP project with Cloud Run, Scheduler, Secret Manager APIs enabled
#   - At least one LLM API key stored in Secret Manager:
#     echo -n "sk-ant-..." | gcloud secrets create anthropic-api-key --data-file=-
#     # For OpenAI:  echo -n "sk-..." | gcloud secrets create openai-api-key --data-file=-
#     # For Gemini:  echo -n "..."    | gcloud secrets create gemini-api-key --data-file=-
# ============================================================

set -euo pipefail

# --- Configuration (edit these) ---
PROJECT_ID="${GCP_PROJECT_ID:-claudio-489311}"
REGION="${GCP_REGION:-europe-west1}"
JOB_NAME="ai-news-scanner"
BUCKET_NAME="${GCS_BUCKET:-gl-ai-news}"
SCHEDULE="${SCAN_SCHEDULE:-0 7 * * *}"  # Default: 7:00 CET daily
TIMEZONE="${SCAN_TIMEZONE:-Europe/Rome}"
LLM_ENV_VAR="${LLM_ENV_VAR:-ANTHROPIC_API_KEY}"
LLM_SECRET_NAME="${LLM_SECRET_NAME:-anthropic-api-key}"
SCHEDULER_SA_NAME="${SCHEDULER_SA_NAME:-ai-news-scheduler}"
SCHEDULER_SA_EMAIL="$SCHEDULER_SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "=== AI News Scanner — Deploy ==="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Bucket:   $BUCKET_NAME"
echo "Schedule: $SCHEDULE ($TIMEZONE)"
echo "LLM secret: $LLM_ENV_VAR <- $LLM_SECRET_NAME"
echo ""

# 0. Fail-closed preflight: project and required LLM secret must exist.
echo "--- Preflight ---"
gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null
if ! gcloud secrets describe "$LLM_SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "ERROR: required secret '$LLM_SECRET_NAME' not found in project '$PROJECT_ID'." >&2
  exit 2
fi

# 1. Create GCS bucket (if not exists)
echo "--- Creating GCS bucket ---"
if gcloud storage buckets describe "gs://$BUCKET_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "Bucket already exists."
else
  gcloud storage buckets create "gs://$BUCKET_NAME" --location="$REGION" --project="$PROJECT_ID"
fi

# 2. Build and push container image
echo "--- Building container image ---"
gcloud builds submit \
  --tag "gcr.io/$PROJECT_ID/$JOB_NAME" \
  --project "$PROJECT_ID"

# 3. Create/update Cloud Run Job
echo "--- Deploying Cloud Run Job ---"
gcloud run jobs deploy "$JOB_NAME" \
  --image "gcr.io/$PROJECT_ID/$JOB_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --set-env-vars "GCS_BUCKET=$BUCKET_NAME" \
  --set-secrets "$LLM_ENV_VAR=$LLM_SECRET_NAME:latest" \
  --max-retries 1 \
  --timeout 300

# 4. Create/update Cloud Scheduler
echo "--- Setting up Cloud Scheduler ---"
if ! gcloud iam service-accounts describe "$SCHEDULER_SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SCHEDULER_SA_NAME" \
    --display-name "AI News Scanner Scheduler" \
    --project "$PROJECT_ID"
fi

gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$SCHEDULER_SA_EMAIL" \
  --role roles/run.invoker >/dev/null

SCHEDULER_ARGS=(
  --location "$REGION"
  --schedule "$SCHEDULE"
  --time-zone "$TIMEZONE"
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run"
  --http-method POST
  --oauth-service-account-email "$SCHEDULER_SA_EMAIL"
  --project "$PROJECT_ID"
)

if gcloud scheduler jobs describe "$JOB_NAME-trigger" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$JOB_NAME-trigger" "${SCHEDULER_ARGS[@]}"
else
  gcloud scheduler jobs create http "$JOB_NAME-trigger" "${SCHEDULER_ARGS[@]}"
fi

echo ""
echo "=== Deploy complete ==="
echo "Schedule: $SCHEDULE $TIMEZONE"
echo "Cost: ~\$0.003/execution (Haiku scoring + Cloud Run)"
echo ""
echo "Manual test:"
echo "  gcloud run jobs execute $JOB_NAME --region $REGION --project $PROJECT_ID"
