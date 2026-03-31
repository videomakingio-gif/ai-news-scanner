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
PROJECT_ID="${GCP_PROJECT_ID:-giovanniliguori-it}"
REGION="${GCP_REGION:-europe-west1}"
JOB_NAME="ai-news-scanner"
BUCKET_NAME="${GCS_BUCKET:-gl-ai-news}"
SCHEDULE="${SCAN_SCHEDULE:-0 7 * * *}"  # Default: 7:00 CET daily
TIMEZONE="${SCAN_TIMEZONE:-Europe/Rome}"

echo "=== AI News Scanner — Deploy ==="
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Bucket:   $BUCKET_NAME"
echo "Schedule: $SCHEDULE ($TIMEZONE)"
echo ""

# 1. Create GCS bucket (if not exists)
echo "--- Creating GCS bucket ---"
gsutil mb -l "$REGION" "gs://$BUCKET_NAME" 2>/dev/null || echo "Bucket already exists."

# 2. Build and push container image
echo "--- Building container image ---"
gcloud builds submit \
  --tag "gcr.io/$PROJECT_ID/$JOB_NAME" \
  --project "$PROJECT_ID"

# 3. Create/update Cloud Run Job
echo "--- Deploying Cloud Run Job ---"
gcloud run jobs replace --region "$REGION" --project "$PROJECT_ID" - <<EOF
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: $JOB_NAME
spec:
  template:
    spec:
      template:
        spec:
          containers:
          - image: gcr.io/$PROJECT_ID/$JOB_NAME
            env:
            # Default: Anthropic. To use OpenAI or Gemini instead, change the
            # secret name and env var below. Supported combinations:
            #   ANTHROPIC_API_KEY -> anthropic-api-key
            #   OPENAI_API_KEY   -> openai-api-key
            #   GEMINI_API_KEY   -> gemini-api-key
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: anthropic-api-key
                  key: latest
            - name: GCS_BUCKET
              value: $BUCKET_NAME
            resources:
              limits:
                memory: 256Mi
                cpu: "1"
          timeoutSeconds: 180
          maxRetries: 1
EOF

# 4. Create/update Cloud Scheduler
echo "--- Setting up Cloud Scheduler ---"
gcloud scheduler jobs create http "$JOB_NAME-trigger" \
  --location "$REGION" \
  --schedule "$SCHEDULE" \
  --time-zone "$TIMEZONE" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
  --http-method POST \
  --oauth-service-account-email "$PROJECT_ID@appspot.gserviceaccount.com" \
  --project "$PROJECT_ID" \
  2>/dev/null || \
gcloud scheduler jobs update http "$JOB_NAME-trigger" \
  --location "$REGION" \
  --schedule "$SCHEDULE" \
  --time-zone "$TIMEZONE" \
  --project "$PROJECT_ID"

echo ""
echo "=== Deploy complete ==="
echo "Schedule: $SCHEDULE $TIMEZONE"
echo "Cost: ~\$0.003/execution (Haiku scoring + Cloud Run)"
echo ""
echo "Manual test:"
echo "  gcloud run jobs execute $JOB_NAME --region $REGION"
