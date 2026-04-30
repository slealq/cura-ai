#!/usr/bin/env bash
# Show status of all Azure DEV environment resources.
set -euo pipefail

RG="rg-imggen-dev"
PG_NAME="psql-imggen-dev2"
REDIS_NAME="redis-imggen-dev"
APPS=("cae-imggen-dev-backend" "cae-imggen-dev-celery-worker" "cae-imggen-dev-celery-clustering" "cae-imggen-dev-celery-generation")

echo "=== Azure DEV Environment Status ==="
echo ""

# PostgreSQL
echo "--- PostgreSQL ($PG_NAME) ---"
PG_STATE=$(az postgres flexible-server show --resource-group "$RG" --name "$PG_NAME" --query "state" -o tsv 2>/dev/null || echo "NOT FOUND")
echo "  State: $PG_STATE"
echo ""

# Redis
echo "--- Redis ($REDIS_NAME) ---"
REDIS_STATE=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "provisioningState" -o tsv 2>/dev/null || echo "NOT FOUND")
echo "  State: $REDIS_STATE"
echo ""

# Container Apps
echo "--- Container Apps ---"
for APP in "${APPS[@]}"; do
    ACTIVE_REVISIONS=$(az containerapp revision list --resource-group "$RG" --name "$APP" \
        --query "length([?properties.active])" -o tsv 2>/dev/null || echo "0")
    if [ "$ACTIVE_REVISIONS" = "0" ]; then
        echo "  $APP: STOPPED (no active revisions)"
    else
        MIN=$(az containerapp show --resource-group "$RG" --name "$APP" --query "properties.template.scale.minReplicas" -o tsv 2>/dev/null || echo "?")
        MAX=$(az containerapp show --resource-group "$RG" --name "$APP" --query "properties.template.scale.maxReplicas" -o tsv 2>/dev/null || echo "?")
        REPLICAS=$(az containerapp replica list --resource-group "$RG" --name "$APP" --query "length(@)" -o tsv 2>/dev/null || echo "?")
        echo "  $APP: replicas=$REPLICAS (min=$MIN, max=$MAX)"
    fi
done

echo ""
echo "=== Done ==="
