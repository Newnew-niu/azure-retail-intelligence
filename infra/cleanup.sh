#!/usr/bin/env bash
# Delete every billable resource created by infra/provision.sh.
#
#   bash infra/cleanup.sh          # asks for confirmation
#   bash infra/cleanup.sh --yes    # no prompt
#
# Deleting the resource group removes the storage account (and the uploaded data),
# the SQL server and database, and the Data Factory with its pipelines and run history.
# The budget lives on the subscription, not in the group, so it is deleted separately.
# Source code, SQL scripts and the ADF pipeline JSON stay in git, so everything can be
# recreated with provision.sh + deployment.
set -euo pipefail
export MSYS_NO_PATHCONV=1

RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-retail-intel-dev}"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

echo "Resources in ${RESOURCE_GROUP}:"
az resource list -g "$RESOURCE_GROUP" --query "[].{name:name, type:type}" -o table

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Permanently delete resource group ${RESOURCE_GROUP} and the budget? Type the group name to confirm: " answer
  [[ "$answer" == "$RESOURCE_GROUP" ]] || { echo "Cancelled."; exit 1; }
fi

az group delete -n "$RESOURCE_GROUP" --yes
az rest --method delete \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.Consumption/budgets/budget-retail-intel?api-version=2023-05-01"

echo "Deleted. Check: az group exists -n ${RESOURCE_GROUP}  (should print false)"
