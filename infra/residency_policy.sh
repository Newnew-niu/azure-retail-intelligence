#!/usr/bin/env bash
# Enforce EU data residency on the subscription with two built-in Azure Policy definitions:
#   "Allowed locations"                      - every new resource must be in an approved region
#   "Allowed locations for resource groups"  - every new resource group too
# The approved regions are read from infra/approved_regions.txt (EU regions only).
#
#   bash infra/residency_policy.sh plan      # print what would be assigned; changes nothing
#   bash infra/residency_policy.sh assign    # create or update both assignments (requires `az login`)
#   bash infra/residency_policy.sh show      # list the location assignments that apply
#   bash infra/residency_policy.sh delete    # remove both assignments (asks first)
#
# Policy denies new deployments outside the list; it does not move or delete existing resources.
# Resources with location "global" are exempt by the definition itself. Checked by
# scripts/access_review.py (GOVERNANCE.md control C17).
set -euo pipefail
export MSYS_NO_PATHCONV=1   # stop Git Bash on Windows rewriting /subscriptions/... into file paths

HERE="$(cd "$(dirname "$0")" && pwd)"
REGIONS_FILE="$HERE/approved_regions.txt"
DEF_RESOURCES="e56962a6-4747-49cd-b67b-bf8b01975c4c"   # Allowed locations
DEF_GROUPS="e765b5de-1225-4ba3-bd56-1ac6695af988"      # Allowed locations for resource groups

approved() { sed -e 's/#.*//' -e 's/[[:space:]]//g' "$REGIONS_FILE" | grep -v '^$'; }

regions_json() {  # approved regions that exist in this cloud, as a JSON array
  local available region list=""
  available=$(az account list-locations --query "[].name" -o tsv | tr -d '\r')
  for region in $(approved); do
    if grep -qx "$region" <<<"$available"; then list+="\"$region\","
    else echo "  skipped: $region is not a region in this cloud" >&2; fi
  done
  [[ -n "$list" ]] || { echo "No approved region exists in this cloud." >&2; exit 1; }
  printf '[%s]' "${list%,}"
}

scope() { printf '/subscriptions/%s' "$(az account show --query id -o tsv)"; }

check_definitions() {
  local name
  for def in "$DEF_RESOURCES" "$DEF_GROUPS"; do
    name=$(az policy definition show --name "$def" --query displayName -o tsv)
    echo "  definition $def: $name"
  done
}

plan() {
  echo "Subscription: $(az account show --query name -o tsv)"
  check_definitions
  echo "Allowed regions: $(regions_json)"
  echo "Assignments: eu-residency-resources, eu-residency-groups (enforced)"
}

assign() {
  local regions params sc
  regions=$(regions_json); sc=$(scope)
  check_definitions
  params="{\"listOfAllowedLocations\": {\"value\": $regions}}"
  az policy assignment create --name eu-residency-resources --scope "$sc" \
    --display-name "EU data residency: allowed locations for resources" \
    --policy "$DEF_RESOURCES" --params "$params" --enforcement-mode Default \
    --description "Approved regions from infra/approved_regions.txt (GOVERNANCE.md C17)" \
    --query "{name:name, enforcement:enforcementMode}" -o tsv
  az policy assignment create --name eu-residency-groups --scope "$sc" \
    --display-name "EU data residency: allowed locations for resource groups" \
    --policy "$DEF_GROUPS" --params "$params" --enforcement-mode Default \
    --description "Approved regions from infra/approved_regions.txt (GOVERNANCE.md C17)" \
    --query "{name:name, enforcement:enforcementMode}" -o tsv
}

show() {
  az policy assignment list --disable-scope-strict-match --scope "$(scope)" \
    --query "[?ends_with(policyDefinitionId, '$DEF_RESOURCES') || ends_with(policyDefinitionId, '$DEF_GROUPS')].{name:name, display:displayName, enforcement:enforcementMode, scope:scope}" \
    -o table
}

delete() {
  read -r -p "Remove the eu-residency policy assignments from the subscription? [y/N] " answer
  [[ "$answer" == "y" ]] || { echo "Cancelled."; exit 1; }
  az policy assignment delete --name eu-residency-resources --scope "$(scope)"
  az policy assignment delete --name eu-residency-groups --scope "$(scope)"
}

case "${1:-}" in
  plan) plan ;;
  assign) assign ;;
  show) show ;;
  delete) delete ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
