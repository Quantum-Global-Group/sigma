#!/usr/bin/env bash
# start_worker.sh — Start the sigma trading worker on the DGX (or any local machine).
#
# Usage:
#   ./scripts/start_worker.sh                        # equity + forex (default)
#   ./scripts/start_worker.sh equity                 # equity only
#   ./scripts/start_worker.sh forex                  # forex only
#   ./scripts/start_worker.sh equity,forex,crypto    # all three
#
# Prerequisites:
#   1. apps/api/.env populated (copy from .env.example and fill credentials)
#   2. Python venv built:  cd apps/api && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#
# The script will:
#   - Verify the venv and .env exist
#   - Print a connectivity summary (Alpaca, OANDA, MT5 bridge, DB)
#   - Start the worker loop with the requested asset classes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
WORKER_DIR="$REPO_ROOT/apps/worker"
VENV="$API_DIR/.venv"
ENV_FILE="$API_DIR/.env"
PYTHON="$VENV/bin/python3"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }
err()  { echo -e "${RED}  ✗${NC} $*"; }
hdr()  { echo -e "\n${CYAN}── $* ──${NC}"; }

# ── Asset classes ─────────────────────────────────────────────────────────────
ASSET_CLASSES="${1:-equity,forex}"

hdr "sigma worker  •  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Asset classes : $ASSET_CLASSES"
echo "  Repo root     : $REPO_ROOT"

# ── Pre-flight checks ─────────────────────────────────────────────────────────
hdr "Pre-flight"

if [[ ! -f "$PYTHON" ]]; then
    err "venv not found at $VENV"
    echo "    Run:  cd apps/api && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi
ok "venv found"

if [[ ! -f "$ENV_FILE" ]]; then
    err ".env not found at $ENV_FILE"
    echo "    Run:  cp .env.example apps/api/.env  then fill in credentials"
    exit 1
fi
ok ".env found"

# Load env so we can read config values for the connectivity check
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ── Connectivity checks ───────────────────────────────────────────────────────
hdr "Connectivity"

# Alpaca
ALPACA_OK=false
if [[ -n "${ALPACA_API_KEY:-}" && -n "${ALPACA_SECRET:-}" ]]; then
    if curl -sf --max-time 5 \
        -H "APCA-API-KEY-ID: $ALPACA_API_KEY" \
        -H "APCA-API-SECRET-KEY: $ALPACA_SECRET" \
        "https://paper-api.alpaca.markets/v2/account" > /dev/null 2>&1; then
        ok "Alpaca paper account reachable"
        ALPACA_OK=true
    else
        warn "Alpaca unreachable (will use paper fallback)"
    fi
else
    warn "ALPACA_API_KEY not set — equity will use paper executor"
fi

# OANDA
if [[ -n "${OANDA_API_TOKEN:-}" && -n "${OANDA_ACCOUNT_ID:-}" ]]; then
    if curl -sf --max-time 5 \
        -H "Authorization: Bearer $OANDA_API_TOKEN" \
        "https://api-fxpractice.oanda.com/v3/accounts/$OANDA_ACCOUNT_ID/summary" > /dev/null 2>&1; then
        ok "OANDA practice account reachable"
    else
        warn "OANDA unreachable — forex fallback to paper"
    fi
else
    warn "OANDA_API_TOKEN not set"
fi

# MT5 bridge (optional — only warn if FOREX_MT5_SYMBOLS is set)
MT5_URL="${MT5_BRIDGE_URL:-http://192.168.0.24:8787}"
MT5_SECRET="${MT5_BRIDGE_SECRET:-}"
if [[ -n "${FOREX_MT5_SYMBOLS:-}" ]]; then
    if curl -sf --max-time 4 \
        -H "X-MT5-Bridge-Secret: $MT5_SECRET" \
        "$MT5_URL/health" > /dev/null 2>&1; then
        ok "MT5 bridge reachable ($MT5_URL) — BlackBull active for ${FOREX_MT5_SYMBOLS}"
    else
        warn "MT5 bridge down ($MT5_URL) — MT5 symbols will be skipped this tick"
    fi
fi

# DB (quick TCP check on Timescale Cloud port)
DB_HOST=$(echo "${DATABASE_URL:-}" | grep -oP '(?<=@)[^:/]+' || true)
DB_PORT=$(echo "${DATABASE_URL:-}" | grep -oP '(?<=:)\d+(?=/)' | tail -1 || true)
if [[ -n "$DB_HOST" && -n "$DB_PORT" ]]; then
    if timeout 5 bash -c ">/dev/tcp/$DB_HOST/$DB_PORT" 2>/dev/null; then
        ok "Timescale Cloud reachable ($DB_HOST:$DB_PORT)"
    else
        err "Cannot reach database at $DB_HOST:$DB_PORT"
        echo "    Check DATABASE_URL in apps/api/.env and network connectivity"
        exit 1
    fi
else
    err "DATABASE_URL not set or unparseable in .env"
    exit 1
fi

# ── Redis check (non-fatal) ───────────────────────────────────────────────────
REDIS_HOST=$(echo "${REDIS_URL:-}" | grep -oP '(?<=@)[^:/]+' || true)
if [[ -n "$REDIS_HOST" ]]; then
    if timeout 4 bash -c ">/dev/tcp/$REDIS_HOST/6379" 2>/dev/null; then
        ok "Upstash Redis reachable"
    else
        warn "Redis unreachable — worker will run but singleton lock and heartbeat won't persist"
    fi
fi

# ── Launch ────────────────────────────────────────────────────────────────────
hdr "Starting worker"
echo "  WORKER_ASSET_CLASSES=$ASSET_CLASSES"
echo ""

export WORKER_ASSET_CLASSES="$ASSET_CLASSES"
# apps/api  — config, db, execution, markets, ml, risk, universe
# apps      — makes `import worker.tick` resolve to apps/worker/tick.py
export PYTHONPATH="$API_DIR:$REPO_ROOT/apps:${PYTHONPATH:-}"

# Run from API dir so pydantic-settings resolves .env automatically
cd "$API_DIR"
exec "$PYTHON" "$WORKER_DIR/main.py"
