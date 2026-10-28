#!/usr/bin/env bash
# Provision the Azure resources for the Retail Intelligence Platform (dev environment).
#
#   bash infra/provision.sh            # requires `az login` first
#
# Idempotent: every step is a create-or-update, so rerunning it is safe.
# Cost: see docs in the README; all resources are pay-per-use or free tier
# (the SQL database uses the free offer and auto-pauses when the monthly limit is used up).
# No keys or passwords are created: storage shared-key access is disabled and SQL
# accepts Microsoft Entra authentication only. Remove everything with infra/cleanup.sh.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash on Windows rewriting /subscriptions/... into file paths

LOCATION="${AZURE_LOCATION:-francecentral}"   # the subscription policy does not allow northeurope
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-retail-intel-dev}"
SQL_DATABASE="${SQL_DATABASE_NAME:-retail_intelligence}"
BUDGET_EUR="${BUDGET_EUR:-10}"
TAGS="project=retail-intelligence env=dev"

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
# Short, stable suffix so globally unique names are the same on every rerun
SUFFIX=$(printf '%s' "$SUBSCRIPTION_ID" | md5sum | cut -c1-6)
STORAGE_ACCOUNT="stretailintel${SUFFIX}"
SQL_SERVER="sql-retail-intel-${SUFFIX}"
DATA_FACTORY="adf-retail-intel-${SUFFIX}"

USER_UPN=$(az ad signed-in-user show --query userPrincipalName -o tsv)
USER_OID=$(az ad signed-in-user show --query id -o tsv)

step() { printf '\n== %s\n' "$*"; }

step "Budget alert: EUR ${BUDGET_EUR}/month on the subscription, emails to ${USER_UPN}"
BUDGET_START=$(date -u +%Y-%m-01T00:00:00Z)
az rest --method put \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.Consumption/budgets/budget-retail-intel?api-version=2023-05-01" \
  --body "{
    \"properties\": {
      \"category\": \"Cost\", \"amount\": ${BUDGET_EUR}, \"timeGrain\": \"Monthly\",
      \"timePeriod\": {\"startDate\": \"${BUDGET_START}\"},
      \"notifications\": {
        \"actual50\":     {\"enabled\": true, \"operator\": \"GreaterThanOrEqualTo\", \"threshold\": 50,  \"thresholdType\": \"Actual\",     \"contactEmails\": [\"${USER_UPN}\"]},
        \"actual80\":     {\"enabled\": true, \"operator\": \"GreaterThanOrEqualTo\", \"threshold\": 80,  \"thresholdType\": \"Actual\",     \"contactEmails\": [\"${USER_UPN}\"]},
        \"actual100\":    {\"enabled\": true, \"operator\": \"GreaterThanOrEqualTo\", \"threshold\": 100, \"thresholdType\": \"Actual\",     \"contactEmails\": [\"${USER_UPN}\"]},
        \"forecast100\":  {\"enabled\": true, \"operator\": \"GreaterThanOrEqualTo\", \"threshold\": 100, \"thresholdType\": \"Forecasted\", \"contactEmails\": [\"${USER_UPN}\"]}
      }
    }
  }" --query "{name:name, amount:properties.amount}" -o tsv

step "Resource group ${RESOURCE_GROUP} (${LOCATION})"
az group create -n "$RESOURCE_GROUP" -l "$LOCATION" --tags $TAGS --query properties.provisioningState -o tsv

step "ADLS Gen2 storage account ${STORAGE_ACCOUNT} (hierarchical namespace, no shared keys, no public access)"
az storage account create -n "$STORAGE_ACCOUNT" -g "$RESOURCE_GROUP" -l "$LOCATION" --tags $TAGS \
  --sku Standard_LRS --kind StorageV2 --access-tier Hot --hns true \
  --min-tls-version TLS1_2 --https-only true \
  --allow-blob-public-access false --allow-shared-key-access false \
  --query provisioningState -o tsv
STORAGE_ID=$(az storage account show -n "$STORAGE_ACCOUNT" -g "$RESOURCE_GROUP" --query id -o tsv)
# Created through the management plane, so it works before any data-plane role has propagated
az storage container-rm create --storage-account "$STORAGE_ACCOUNT" -g "$RESOURCE_GROUP" -n raw \
  --public-access off --query name -o tsv

step "Azure SQL logical server ${SQL_SERVER} (Entra-only authentication, admin ${USER_UPN})"
if ! az sql server show -n "$SQL_SERVER" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az sql server create -n "$SQL_SERVER" -g "$RESOURCE_GROUP" -l "$LOCATION" \
    --enable-ad-only-auth --external-admin-principal-type User \
    --external-admin-name "$USER_UPN" --external-admin-sid "$USER_OID" \
    --minimal-tls-version 1.2 --query state -o tsv
fi
az resource tag --ids "$(az sql server show -n "$SQL_SERVER" -g "$RESOURCE_GROUP" --query id -o tsv)" \
  --tags $TAGS -o none

step "SQL firewall: this machine's public IP + Azure services (needed by the ADF Azure integration runtime)"
CLIENT_IP=$(curl -s https://api.ipify.org)
az sql server firewall-rule create -s "$SQL_SERVER" -g "$RESOURCE_GROUP" -n allow-dev-client \
  --start-ip-address "$CLIENT_IP" --end-ip-address "$CLIENT_IP" --query name -o tsv
az sql server firewall-rule create -s "$SQL_SERVER" -g "$RESOURCE_GROUP" -n AllowAllWindowsAzureIps \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 --query name -o tsv

# The free offer fixes the auto-pause delay at 60 minutes (changing it is rejected).
step "SQL database ${SQL_DATABASE} (serverless free offer, auto-pause when the free limit is used up)"
if ! az sql db show -n "$SQL_DATABASE" -s "$SQL_SERVER" -g "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az sql db create -n "$SQL_DATABASE" -s "$SQL_SERVER" -g "$RESOURCE_GROUP" --tags $TAGS \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --capacity 2 \
    --use-free-limit true --free-limit-exhaustion-behavior AutoPause \
    --backup-storage-redundancy Local --query status -o tsv
fi

step "Data Factory ${DATA_FACTORY} (system-assigned managed identity)"
az rest --method put \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.DataFactory/factories/${DATA_FACTORY}?api-version=2018-06-01" \
  --body "{\"location\": \"${LOCATION}\", \"identity\": {\"type\": \"SystemAssigned\"},
           \"tags\": {\"project\": \"retail-intelligence\", \"env\": \"dev\"}}" \
  --query properties.provisioningState -o tsv
ADF_PRINCIPAL_ID=$(az rest --method get \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.DataFactory/factories/${DATA_FACTORY}?api-version=2018-06-01" \
  --query identity.principalId -o tsv)

step "Role assignments (least privilege, scoped to the storage account)"
az role assignment create --assignee-object-id "$ADF_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope "$STORAGE_ID" -o none && echo "ADF identity: Storage Blob Data Reader"
az role assignment create --assignee-object-id "$USER_OID" --assignee-principal-type User \
  --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" -o none && echo "${USER_UPN}: Storage Blob Data Contributor"

step "Done. Put these (non-secret) names in .env:"
cat <<EOF
AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}
AZURE_RESOURCE_GROUP=${RESOURCE_GROUP}
AZURE_STORAGE_ACCOUNT=${STORAGE_ACCOUNT}
AZURE_SQL_SERVER=${SQL_SERVER}.database.windows.net
AZURE_DATA_FACTORY=${DATA_FACTORY}
EOF
