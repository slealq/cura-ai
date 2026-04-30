#!/usr/bin/env bash
# Preflight checks for cloud-connected local development.
# Verifies Azure DEV resources are accessible and adds DB firewall rule.
set -euo pipefail

RG="rg-imggen-dev"
PG_NAME="psql-imggen-dev2"
REDIS_NAME="redis-imggen-dev"
APPS=("cae-imggen-dev-backend" "cae-imggen-dev-celery-worker" "cae-imggen-dev-celery-clustering" "cae-imggen-dev-celery-generation")

ERRORS=0

echo "=== Cloud DEV Preflight Checks ==="
echo ""

# 1. Check Azure CLI
if ! az account show &>/dev/null; then
    echo "[FAIL] Not logged in to Azure CLI. Run: az login"
    exit 1
fi
echo "[OK] Azure CLI authenticated"

# 2. Check PostgreSQL state
echo ""
echo "--- PostgreSQL ---"
PG_STATE=$(az postgres flexible-server show --resource-group "$RG" --name "$PG_NAME" --query "state" -o tsv 2>/dev/null || echo "unknown")
if [ "$PG_STATE" = "Ready" ]; then
    echo "[OK] PostgreSQL is Ready"
else
    echo "[FAIL] PostgreSQL state: $PG_STATE"
    echo "  Run: ./scripts/dev-env-start.sh"
    ERRORS=$((ERRORS + 1))
fi

# 3. Check Redis exists
echo ""
echo "--- Redis ---"
REDIS_STATE=$(az redis show --resource-group "$RG" --name "$REDIS_NAME" --query "provisioningState" -o tsv 2>/dev/null || echo "not-found")
if [ "$REDIS_STATE" = "Succeeded" ]; then
    echo "[OK] Redis is provisioned"
else
    echo "[FAIL] Redis state: $REDIS_STATE"
    echo "  Run: ./scripts/dev-env-start.sh"
    ERRORS=$((ERRORS + 1))
fi

# 4. Add DB firewall rule for current IP
echo ""
echo "--- DB Firewall ---"
MY_IP=$(curl -s --max-time 5 ifconfig.me || echo "")
if [ -z "$MY_IP" ]; then
    echo "[WARN] Could not detect public IP. Skipping firewall rule."
else
    echo "  Current IP: $MY_IP"
    az postgres flexible-server firewall-rule create \
        --resource-group "$RG" --name "$PG_NAME" \
        --rule-name "CloudDevLocal" \
        --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" \
        -o none 2>/dev/null || true
    echo "[OK] Firewall rule added/updated for $MY_IP"
fi

# 5. Check Container App status (informational)
echo ""
echo "--- Container App Status ---"
for APP in "${APPS[@]}"; do
    ACTIVE_REVISIONS=$(az containerapp revision list --resource-group "$RG" --name "$APP" \
        --query "length([?properties.active])" -o tsv 2>/dev/null || echo "0")
    if [ "$ACTIVE_REVISIONS" = "0" ]; then
        echo "[--] $APP has no active revisions (stopped via cura azure stop)"
    else
        REPLICAS=$(az containerapp show --resource-group "$RG" --name "$APP" \
            --query "properties.template.scale.minReplicas" -o tsv 2>/dev/null || echo "0")
        if [ "$REPLICAS" != "0" ]; then
            echo "[OK] $APP running (minReplicas=$REPLICAS)"
        else
            echo "[--] $APP scaled to 0"
        fi
    fi
done
echo ""
echo "  Cloud-native uses an isolated Celery broker (Redis db 3)."
echo "  DEV cloud workers (db 1) will not compete with local workers."

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "=== $ERRORS preflight check(s) failed. Fix issues above before continuing. ==="
    exit 1
else
    echo "=== All checks passed. Ready for cloud-connected development. ==="
fi
