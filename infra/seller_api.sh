#!/usr/bin/env bash
# Host the serving API (Seller Health back end) on Azure Container Apps.
#
#   bash infra/seller_api.sh create <image>    # first deployment; requires `az login`
#   bash infra/seller_api.sh update <image>    # new image, same data and settings
#   bash infra/seller_api.sh data              # upload a new data/serving.duckdb and restart
#   bash infra/seller_api.sh url               # print the public URL
#   bash infra/seller_api.sh delete            # remove everything (asks first)
#
# <image> is published by .github/workflows/api-image.yml, for example
#   ghcr.io/newnew-niu/azure-retail-intelligence/serving-api:sha-<commit>
#
# Everything lives in its own resource group, so delete removes all of it. Cost: Consumption plan,
# scales to zero, at most one replica of 0.25 vCPU / 0.5 GiB, inside the monthly free grant for
# light use; a 1 GiB file share for the 24 MB DuckDB export. No Log Analytics workspace.
# Secrets are generated here and stored only as Container Apps secrets; nothing is printed.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash on Windows rewriting /data and /subscriptions paths

LOCATION="${AZURE_LOCATION:-francecentral}"
RESOURCE_GROUP="${SELLER_API_RESOURCE_GROUP:-rg-seller-health}"
ENVIRONMENT="cae-seller-health"
APP="seller-api"
SHARE="serving-data"
ENV_STORAGE="servingdata"
WEB_ORIGIN="${SELLER_API_CORS_ORIGIN:-https://newnew-niu.github.io}"
DATA_FILE="data/serving.duckdb"
TAGS="project=retail-intelligence component=seller-health"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
SUFFIX=$(printf '%s' "$SUBSCRIPTION_ID" | md5sum | cut -c1-6)
STORAGE_ACCOUNT="stsellerhealth${SUFFIX}"

step() { printf '\n== %s\n' "$*"; }

storage_key() {
  az storage account keys list -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT" --query "[0].value" -o tsv
}

upload_data() {
  [[ -f "$DATA_FILE" ]] || { echo "$DATA_FILE not found. Run scripts/export_serving_db.py first."; exit 1; }
  step "Upload $DATA_FILE to the file share"
  az storage file upload --only-show-errors --account-name "$STORAGE_ACCOUNT" --account-key "$(storage_key)" \
    --share-name "$SHARE" --source "$DATA_FILE" --path serving.duckdb >/dev/null
}

app_yaml() {  # image api_key storage -> YAML on stdout; written to a private temporary file by the caller
  local environment_id
  environment_id=$(az containerapp env show -g "$RESOURCE_GROUP" -n "$ENVIRONMENT" --query id -o tsv)
  cat <<YAML
location: ${LOCATION}
properties:
  managedEnvironmentId: ${environment_id}
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      targetPort: 8000
      transport: auto
      allowInsecure: false
    secrets:
      - name: serving-api-key
        value: ${2}
  template:
    containers:
      - name: api
        image: ${1}
        resources:
          cpu: 0.25
          memory: 0.5Gi
        env:
          - name: SERVING_API_KEY
            secretRef: serving-api-key
          - name: SERVING_CORS_ORIGINS
            value: ${WEB_ORIGIN}
          - name: SERVING_BACKEND
            value: duckdb
        volumeMounts:
          - volumeName: serving-data
            mountPath: /data
        probes:
          - type: Liveness
            httpGet:
              path: /health
              port: 8000
            periodSeconds: 30
          - type: Readiness
            httpGet:
              path: /health
              port: 8000
            periodSeconds: 10
    scale:
      minReplicas: 0
      maxReplicas: 1
      rules:
        - name: http
          http:
            metadata:
              concurrentRequests: "20"
    volumes:
      - name: serving-data
        storageType: AzureFile
        storageName: ${ENV_STORAGE}
tags:
  project: retail-intelligence
  component: seller-health
YAML
}

create() {
  local image=$1
  step "Register the Container Apps resource provider (once per subscription)"
  az provider register -n Microsoft.App --wait
  az extension add -n containerapp --upgrade --only-show-errors

  step "Resource group $RESOURCE_GROUP in $LOCATION"
  az group create -n "$RESOURCE_GROUP" -l "$LOCATION" --tags $TAGS -o none

  step "Storage account $STORAGE_ACCOUNT and file share $SHARE"
  az storage account create -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT" -l "$LOCATION" --sku Standard_LRS \
    --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false --https-only true \
    --tags $TAGS -o none
  az storage share-rm create -g "$RESOURCE_GROUP" --storage-account "$STORAGE_ACCOUNT" -n "$SHARE" --quota 1 -o none
  upload_data

  step "Container Apps environment $ENVIRONMENT (Consumption, no Log Analytics)"
  az containerapp env create -g "$RESOURCE_GROUP" -n "$ENVIRONMENT" -l "$LOCATION" \
    --logs-destination none --tags $TAGS -o none
  az containerapp env storage set -g "$RESOURCE_GROUP" -n "$ENVIRONMENT" --storage-name "$ENV_STORAGE" \
    --azure-file-account-name "$STORAGE_ACCOUNT" --azure-file-account-key "$(storage_key)" \
    --azure-file-share-name "$SHARE" --access-mode ReadOnly -o none

  step "Container app $APP"
  local spec api_key
  spec=$(mktemp)
  trap 'rm -f "$spec"' RETURN
  chmod 600 "$spec"
  api_key=$(openssl rand -base64 32 | tr -d "/+=")
  app_yaml "$image" "$api_key" >"$spec"
  az containerapp create -g "$RESOURCE_GROUP" -n "$APP" --yaml "$spec" -o none
  url
}

update() {
  step "Deploy image $1"
  az containerapp update -g "$RESOURCE_GROUP" -n "$APP" --image "$1" -o none
  url
}

restart() {
  local revision
  revision=$(az containerapp show -g "$RESOURCE_GROUP" -n "$APP" --query properties.latestRevisionName -o tsv)
  az containerapp revision restart -g "$RESOURCE_GROUP" -n "$APP" --revision "$revision" -o none
}

url() {
  printf 'https://%s\n' "$(az containerapp show -g "$RESOURCE_GROUP" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
}

delete() {
  echo "Resources in ${RESOURCE_GROUP}:"
  az resource list -g "$RESOURCE_GROUP" --query "[].{name:name, type:type}" -o table
  if [[ "${1:-}" != "--yes" ]]; then
    read -r -p "Permanently delete resource group ${RESOURCE_GROUP}? Type the group name to confirm: " answer
    [[ "$answer" == "$RESOURCE_GROUP" ]] || { echo "Cancelled."; exit 1; }
  fi
  az group delete -n "$RESOURCE_GROUP" --yes
  echo "Deleted. Check: az group exists -n ${RESOURCE_GROUP}  (should print false)"
}

case "${1:-}" in
  create) create "${2:?image required}" ;;
  update) update "${2:?image required}" ;;
  data) upload_data; restart ;;
  url) url ;;
  delete) delete "${2:-}" ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
