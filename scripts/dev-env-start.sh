#!/usr/bin/env bash
# Start all Azure DEV environment resources.
# - Starts PostgreSQL Flexible Server
# - Recreates Redis (Basic SKU, deleted by stop script)
# - Updates Container App secrets with new Redis key
# - Scales Container Apps back to original replicas
# - Polls for backend health
# - Adds DB firewall rule for current IP
set -euo pipefail

RG="rg-imggen-dev"
PG_NAME="psql-imggen-dev2"
REDIS_NAME="redis-imggen-dev"
REDIS_SKU="Basic"
REDIS_SIZE="C0"
APPS=("cae-imggen-dev-backend" "cae-imggen-dev-celery-worker" "cae-imggen-dev-celery-clustering" "cae-imggen-dev-celery-generation")
BACKEND_URL="https://cae-imggen-dev-backend.ambitioussand-1e60af3e.eastus.azurecontainerapps.io"

echo "=== Starting Azure DEV Environment ==="

# 1. Start PostgreSQL
echo ""
echo "--- Starting PostgreSQL ($PG_NAME) ---"
PG_STATE=$(az postgres flexible-server show --resource-group "$RG" --name "$PG_NAME" --query "state" -o tsv 2>/dev/null || echo "unknown")
if [ "$PG_STATE" = "Stopped" ]; then
    az postgres flexible-server start --resource-group "$RG" --name "$PG_NAME"
    echo "  PostgreSQL start initiated. Waiting for Ready state..."
    while true; do
        STATE=$(az postgres flexible-server show --resource-group "$RG" --name "$PG_NAME" --query "state" -o tsv 2>/dev/null || echo "unknown")
        if [ "$STATE" = "Ready" ]; then
            echo "  PostgreSQL is Ready."
            break
        fi
        echo "  State: $STATE (waiting 10s...)"
        sleep 10
    done
elif [ "$PG_STATE" = "Ready" ]; then
    echo "  PostgreSQL already running."
else
    echo "  PostgreSQL in state: $PG_STATE"
fi

# 2. Recreate Redis
echo ""
echo "--- Creating Redis ($REDIS_NAME) ---"
REDIS_EXISTS=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "name" -o tsv 2>/dev/null || echo "")
if [ -z "$REDIS_EXISTS" ]; then
    echo "  Creating Redis (Basic C0). This takes 5-10 minutes..."
    az redis create --resource-group "$RG" --name "$REDIS_NAME" \
        --location eastus --sku "$REDIS_SKU" --vm-size "$REDIS_SIZE" \
        --redis-version 6 --enable-non-ssl-port -o none

    # Poll until provisioning completes
    while true; do
        REDIS_STATE=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "provisioningState" -o tsv 2>/dev/null || echo "unknown")
        if [ "$REDIS_STATE" = "Succeeded" ]; then
            echo "  Redis provisioned successfully."
            break
        fi
        echo "  Provisioning state: $REDIS_STATE (waiting 15s...)"
        sleep 15
    done
else
    echo "  Redis already exists."
fi

# 3. Get Redis access key and update Container App secrets
echo ""
echo "--- Updating Container App secrets with new Redis key ---"
REDIS_HOST=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "hostName" -o tsv)
REDIS_KEY=$(az redis list-keys --resource-group "$RG" --name "$REDIS_NAME" --query "primaryKey" -o tsv)
REDIS_PORT=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "sslPort" -o tsv)
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:${REDIS_PORT}/0"

for APP in "${APPS[@]}"; do
    echo "  Updating $APP..."
    az containerapp secret set --resource-group "$RG" --name "$APP" \
        --secrets "redis-url=${REDIS_URL}" -o none 2>/dev/null || true
done
echo "  Secrets updated."

# 4. Scale Container Apps back up
echo ""
echo "--- Scaling Container Apps ---"
# Match actual Azure config: backend 1/3, workers 1/2, clustering 1/1, generation 1/2
declare -A SCALE_CONFIG
SCALE_CONFIG["cae-imggen-dev-backend"]="1 3"
SCALE_CONFIG["cae-imggen-dev-celery-worker"]="1 2"
SCALE_CONFIG["cae-imggen-dev-celery-clustering"]="1 1"
SCALE_CONFIG["cae-imggen-dev-celery-generation"]="1 2"

PIDS=()
for APP in "${APPS[@]}"; do
    read -r MIN MAX <<< "${SCALE_CONFIG[$APP]}"
    echo "  Scaling $APP to min=$MIN max=$MAX..."
    az containerapp update --resource-group "$RG" --name "$APP" \
        --min-replicas "$MIN" --max-replicas "$MAX" -o none &
    PIDS+=($!)
done
for PID in "${PIDS[@]}"; do
    wait "$PID"
done
echo "  All Container Apps scaled."

# 5. Health check
echo ""
echo "--- Waiting for backend health check ---"
for i in $(seq 1 30); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BACKEND_URL}/api/docs" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  Backend is healthy (HTTP 200)."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  WARNING: Backend did not respond after 5 minutes. Check logs."
        break
    fi
    echo "  Attempt $i/30: HTTP $HTTP_CODE (waiting 10s...)"
    sleep 10
done

# 6. Add DB firewall rule for current IP
echo ""
echo "--- Adding DB firewall rule for current IP ---"
MY_IP=$(curl -s ifconfig.me)
az postgres flexible-server firewall-rule create \
    --resource-group "$RG" --name "$PG_NAME" \
    --rule-name "AllowLocalDev" \
    --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" \
    -o none 2>/dev/null || true
echo "  Firewall rule added for $MY_IP"

echo ""
echo "=== DEV environment is up ==="
echo "  Backend: $BACKEND_URL"
echo "  API docs: ${BACKEND_URL}/api/docs"
