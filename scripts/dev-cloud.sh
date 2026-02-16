#!/usr/bin/env bash
# Start cloud-connected native development with hot-reload.
# Runs backend (uvicorn), 3 Celery workers, and frontend (next dev) locally,
# all connected to Azure DEV resources (PostgreSQL, Redis, Blob Storage).
#
# Usage: ./scripts/dev-cloud.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.cloud"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Track child PIDs for cleanup
PIDS=()

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down all processes...${NC}"
    for PID in "${PIDS[@]}"; do
        kill "$PID" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo -e "${GREEN}All processes stopped.${NC}"
}
trap cleanup EXIT INT TERM

# --- Pre-checks ---

# 1. Check .env.cloud exists
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}ERROR: $ENV_FILE not found.${NC}"
    echo "Run: ./scripts/setup-cloud-env.sh"
    exit 1
fi

echo -e "${CYAN}=== Cloud DEV Native Development ===${NC}"
echo ""

# 2. Load env vars
set -a
source "$ENV_FILE"
# Also load root .env for API keys (cloud env vars take precedence)
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi
# Re-source cloud env to override any root .env values
source "$ENV_FILE"
set +a

# 2b. Isolate Celery broker from DEV cloud workers.
#     DEV Container Apps use Redis db 1. Cloud-native uses db 3 so local
#     and cloud workers never compete for the same tasks.
export CELERY_BROKER_URL="${CELERY_BROKER_URL%/*}/3"

# 3. Run preflight checks
echo -e "${CYAN}--- Running preflight checks ---${NC}"
"$SCRIPT_DIR/ensure-cloud-access.sh"
echo ""

# 4. Test DB connectivity
echo -e "${CYAN}--- Testing database connectivity ---${NC}"
if command -v pg_isready &>/dev/null; then
    PG_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    PG_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
    if pg_isready -h "$PG_HOST" -p "${PG_PORT:-5432}" -t 5 &>/dev/null; then
        echo -e "${GREEN}[OK] PostgreSQL is reachable${NC}"
    else
        echo -e "${RED}[FAIL] Cannot reach PostgreSQL at $PG_HOST:${PG_PORT:-5432}${NC}"
        echo "  Check your firewall rule and DB password in .env.cloud"
        exit 1
    fi
else
    # Fallback: try a quick Python connection test
    if python3 -c "
import urllib.parse, socket, sys
url = urllib.parse.urlparse('$DATABASE_URL')
try:
    s = socket.create_connection((url.hostname, url.port or 5432), timeout=5)
    s.close()
except Exception as e:
    print(f'Cannot reach DB: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        echo -e "${GREEN}[OK] PostgreSQL is reachable${NC}"
    else
        echo -e "${RED}[FAIL] Cannot reach PostgreSQL${NC}"
        echo "  Check your firewall rule and DB password in .env.cloud"
        exit 1
    fi
fi

# 5. Test Redis connectivity
echo -e "${CYAN}--- Testing Redis connectivity ---${NC}"
REDIS_HOST=$(echo "$REDIS_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
REDIS_PORT=$(echo "$REDIS_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
REDIS_PASS=$(echo "$REDIS_URL" | sed -n 's|.*://:\([^@]*\)@.*|\1|p')

if command -v redis-cli &>/dev/null; then
    if redis-cli -h "$REDIS_HOST" -p "${REDIS_PORT:-6380}" -a "$REDIS_PASS" --tls ping 2>/dev/null | grep -q PONG; then
        echo -e "${GREEN}[OK] Redis is reachable${NC}"
    else
        echo -e "${RED}[FAIL] Cannot reach Redis at $REDIS_HOST:${REDIS_PORT:-6380}${NC}"
        echo "  Redis key may be stale. Re-run: ./scripts/setup-cloud-env.sh"
        exit 1
    fi
else
    # Fallback: just check TCP connectivity
    if python3 -c "
import socket, sys
try:
    s = socket.create_connection(('$REDIS_HOST', ${REDIS_PORT:-6380}), timeout=5)
    s.close()
except Exception as e:
    print(f'Cannot reach Redis: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        echo -e "${GREEN}[OK] Redis port is reachable (no redis-cli for PING test)${NC}"
    else
        echo -e "${RED}[FAIL] Cannot reach Redis at $REDIS_HOST:${REDIS_PORT:-6380}${NC}"
        echo "  Is the DEV environment running? Run: ./scripts/dev-env-start.sh"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}=== All checks passed. Starting services... ===${NC}"
echo ""

# --- Start services ---

# Backend (uvicorn with hot-reload on port 8001)
echo -e "${CYAN}[backend]${NC} Starting uvicorn on :8001..."
cd "$PROJECT_ROOT/backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001 2>&1 | sed "s/^/[backend] /" &
PIDS+=($!)

# Celery worker (default queue)
# Use --pool=threads to avoid macOS fork() SIGSEGV with C extensions (Pillow, numpy, imagehash)
echo -e "${CYAN}[celery]${NC} Starting default queue worker..."
celery -A app.workers.celery_app worker --loglevel=info --pool=threads --concurrency=4 2>&1 | sed "s/^/[celery] /" &
PIDS+=($!)

# Celery worker (clustering queue)
echo -e "${CYAN}[clustering]${NC} Starting clustering queue worker..."
celery -A app.workers.celery_app worker --loglevel=info --pool=threads --concurrency=2 -Q clustering 2>&1 | sed "s/^/[clustering] /" &
PIDS+=($!)

# Celery worker (generation queue)
echo -e "${CYAN}[generation]${NC} Starting generation queue worker..."
celery -A app.workers.celery_app worker --loglevel=info --pool=threads --concurrency=2 -Q generation 2>&1 | sed "s/^/[generation] /" &
PIDS+=($!)
cd "$PROJECT_ROOT"

# Frontend (next dev on port 3001, proxying to local backend on 8001)
echo -e "${CYAN}[frontend]${NC} Starting Next.js dev on :3001..."
cd "$PROJECT_ROOT/frontend"
NEXT_PUBLIC_ENV_LABEL=cloud-native INTERNAL_API_URL=http://localhost:8001 npm run dev -- --port 3001 2>&1 | sed "s/^/[frontend] /" &
PIDS+=($!)
cd "$PROJECT_ROOT"

echo ""
echo -e "${GREEN}=== All services started ===${NC}"
echo -e "  Frontend: ${CYAN}http://localhost:3001${NC}"
echo -e "  Backend:  ${CYAN}http://localhost:8001${NC}"
echo -e "  API Docs: ${CYAN}http://localhost:8001/api/docs${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

# Wait for frontend, warmup all routes, then open browser
(
    attempts=0
    while ! lsof -i :3001 -sTCP:LISTEN >/dev/null 2>&1; do
        sleep 1
        attempts=$((attempts + 1))
        [ "$attempts" -ge 60 ] && exit 0
    done
    sleep 2

    # Pre-compile all pages so there's no delay on first visit
    echo -e "${CYAN}[warmup]${NC} Pre-compiling all pages..."
    ROUTES=(
        /
        /login
        /images
        /images/all
        /upload
        /search
        /jobs
        /models
        /generate
        /settings
        /debug
        /clusters/0
        /images/folder/0
    )
    for route in "${ROUTES[@]}"; do
        curl -s -o /dev/null "http://localhost:3001${route}" &
    done
    wait
    echo -e "${GREEN}[warmup]${NC} All pages pre-compiled."

    if [ "${CURA_OPEN_BROWSER:-}" = "1" ]; then
        open -a "Google Chrome" "http://localhost:3001"
    fi
) &

# Wait for any process to exit
wait
