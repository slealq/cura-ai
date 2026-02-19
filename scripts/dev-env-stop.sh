#!/usr/bin/env bash
# Stop all Azure DEV environment resources to save costs.
# - Deactivates Container App revisions (stops all replicas, including Celery workers)
# - Stops PostgreSQL Flexible Server
# - Deletes Redis (Basic SKU has no stop/start — recreate via dev-env-start.sh)
set -euo pipefail

RG="rg-imggen-dev"
PG_NAME="psql-imggen-dev2"
REDIS_NAME="redis-imggen-dev"
APPS=("cae-imggen-dev-backend" "cae-imggen-dev-celery-worker" "cae-imggen-dev-celery-clustering" "cae-imggen-dev-celery-generation")

echo "=== Stopping Azure DEV Environment ==="

# 1. Deactivate all Container App revisions (parallel)
# Scaling to min=0 alone doesn't stop Celery workers (they're not HTTP-triggered).
# Deactivating the active revision guarantees 0 running replicas.
echo ""
echo "--- Deactivating Container App revisions ---"
PIDS=()
for APP in "${APPS[@]}"; do
    (
        REVISION=$(az containerapp revision list --resource-group "$RG" --name "$APP" \
            --query "[?properties.active].name" -o tsv 2>/dev/null || echo "")
        if [ -n "$REVISION" ]; then
            echo "  Deactivating $APP revision: $REVISION"
            az containerapp revision deactivate --resource-group "$RG" --name "$APP" \
                --revision "$REVISION" -o none
        else
            echo "  $APP: no active revision (already deactivated)"
        fi
    ) &
    PIDS+=($!)
done
for PID in "${PIDS[@]}"; do
    wait "$PID"
done
echo "  All Container App revisions deactivated."

# 2. Stop PostgreSQL
echo ""
echo "--- Stopping PostgreSQL ($PG_NAME) ---"
PG_STATE=$(az postgres flexible-server show --resource-group "$RG" --name "$PG_NAME" --query "state" -o tsv 2>/dev/null || echo "unknown")
if [ "$PG_STATE" = "Ready" ]; then
    az postgres flexible-server stop --resource-group "$RG" --name "$PG_NAME"
    echo "  PostgreSQL stop initiated."
else
    echo "  PostgreSQL already in state: $PG_STATE (skipping)"
fi

# 3. Delete Redis (Basic SKU cannot be stopped)
echo ""
echo "--- Deleting Redis ($REDIS_NAME) ---"
REDIS_EXISTS=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "name" -o tsv 2>/dev/null || echo "")
if [ -n "$REDIS_EXISTS" ]; then
    # Save the access key for reference (in case needed before recreation)
    REDIS_KEY=$(az redis list-keys --resource-group "$RG" --name "$REDIS_NAME" --query "primaryKey" -o tsv 2>/dev/null || echo "")
    if [ -n "$REDIS_KEY" ]; then
        echo "$REDIS_KEY" > .redis-key-dev
        echo "  Saved Redis key to .redis-key-dev (for reference)"
    fi
    az redis delete --resource-group "$RG" --name "$REDIS_NAME" --yes
    echo "  Redis deletion initiated."
else
    echo "  Redis not found (already deleted?)."
fi

echo ""
echo "=== DEV environment stopped. Estimated monthly savings: ~\$50-80 ==="
echo "Run ./scripts/dev-env-start.sh to bring it back up."
