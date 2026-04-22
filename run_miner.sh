#!/usr/bin/env bash
# run_miner.sh — pre-flight safety wrapper for the Precog baseline miner
#
# Usage:
#   ./run_miner.sh                     # prompts for confirmation if NETWORK=finney
#   ./run_miner.sh --make_it_rain      # skips mainnet confirmation, no prompts
#
# Environment:
#   PRECOG_DIR   path to the Precog subnet repo (default: ~/precog-node)
#   ENV_FILE     path to the .env.miner file (default: $PRECOG_DIR/.env.miner)
#
# Risk controls read from ENV_FILE:
#   NETWORK              testnet | finney  (default: testnet)
#   RISK_LIMITS_ENABLED  1 | 0             (default: 1)
#   MIN_BALANCE_TAO      float             (default: 1.0)
#   COLDKEY              wallet coldkey name
#   MINER_HOTKEY         wallet hotkey name

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Parse flags ───────────────────────────────────────────────────────────────
MAKE_IT_RAIN=false
for arg in "$@"; do
    [[ "$arg" == "--make_it_rain" ]] && MAKE_IT_RAIN=true
done

# ── Locate env file ───────────────────────────────────────────────────────────
PRECOG_DIR="${PRECOG_DIR:-$HOME/precog-node}"
ENV_FILE="${ENV_FILE:-$PRECOG_DIR/.env.miner}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: env file not found: $ENV_FILE"
    echo "  Run deploy.sh first, then edit $ENV_FILE"
    exit 1
fi

# Load env vars from file as defaults — env vars already in the environment take priority.
while IFS='=' read -r _key _value; do
    _key="${_key// /}"  # trim whitespace
    [[ -n "$_key" ]] && [[ "$_key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && \
        ! printenv "$_key" > /dev/null 2>&1 && \
        export "$_key=$_value"
done < <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | grep '=')

# ── Defaults ──────────────────────────────────────────────────────────────────
NETWORK="${NETWORK:-testnet}"
RISK_LIMITS_ENABLED="${RISK_LIMITS_ENABLED:-1}"
MIN_BALANCE_TAO="${MIN_BALANCE_TAO:-1.0}"
COLDKEY="${COLDKEY:-miner}"
MINER_HOTKEY="${MINER_HOTKEY:-default}"
MINER_NAME="${MINER_NAME:-baseline-miner}"
MINER_PORT="${MINER_PORT:-8092}"
TIMEOUT="${TIMEOUT:-16}"
VPERMIT_TAO_LIMIT="${VPERMIT_TAO_LIMIT:-2}"
FORWARD_FUNCTION="${FORWARD_FUNCTION:-baseline_miner}"
LOGGING_LEVEL="${LOGGING_LEVEL:-info}"

# Map LOGGING_LEVEL → bt.logging boolean flag (bt.logging ignores --logging.level)
case "$LOGGING_LEVEL" in
    trace) _BT_LOG_FLAG="--logging.trace" ;;
    debug) _BT_LOG_FLAG="--logging.debug" ;;
    *)     _BT_LOG_FLAG="--logging.info"  ;;
esac

# ── Network → chain endpoint + netuid ─────────────────────────────────────────
case "$NETWORK" in
    testnet)  _CHAIN="wss://test.finney.opentensor.ai:443"; _NETUID=256 ;;
    finney)   _CHAIN="wss://entrypoint-finney.opentensor.ai:443"; _NETUID=55 ;;
    localnet) _CHAIN="${LOCAL_SUBTENSOR:-ws://127.0.0.1:9945}"; _NETUID=55 ;;
    *)        echo "ERROR: Unknown NETWORK=$NETWORK"; exit 1 ;;
esac

# ── Log directory setup ───────────────────────────────────────────────────────
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
RUN_TS=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
OUT_LOG="$LOG_DIR/${MINER_NAME}-${RUN_TS}-out.log"
ERR_LOG="$LOG_DIR/${MINER_NAME}-${RUN_TS}-err.log"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Precog Baseline Miner — Pre-flight Check        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Network     : $NETWORK (netuid $_NETUID)"
echo "  Coldkey     : $COLDKEY"
echo "  Hotkey      : $MINER_HOTKEY"
echo "  Risk limits : $RISK_LIMITS_ENABLED"
echo "  Min balance : ${MIN_BALANCE_TAO} τ"
echo "  Make it rain: $MAKE_IT_RAIN"
echo "  Log dir     : $LOG_DIR"
echo ""

# ── btcli version check ───────────────────────────────────────────────────────
_BTCLI_PIN_FILE="$SCRIPT_DIR/.btcli-version"
if [[ -f "$_BTCLI_PIN_FILE" ]]; then
    _PINNED_VER=$(cat "$_BTCLI_PIN_FILE")
    _ACTUAL_VER=$(btcli --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "unknown")
    if [[ "$_ACTUAL_VER" != "$_PINNED_VER" ]]; then
        echo "⚠️  btcli version mismatch: installed=$_ACTUAL_VER pinned=$_PINNED_VER"
        echo "   Re-run deploy.sh to install the correct version."
        if [[ "$RISK_LIMITS_ENABLED" == "1" ]]; then
            exit 1
        fi
    else
        echo "  ✓ btcli $_ACTUAL_VER (matches pinned)"
    fi
fi
echo ""

# ── Risk: mainnet confirmation ────────────────────────────────────────────────
if [[ "$NETWORK" == "finney" ]]; then
    if [[ "$MAKE_IT_RAIN" == "true" ]]; then
        echo "⚡ --make_it_rain set — skipping mainnet confirmation."
    else
        echo "⚠️  WARNING: NETWORK=finney — this will run on MAINNET with real TAO."
        echo ""
        read -rp "   Type 'yes' to continue, anything else to abort: " _confirm
        if [[ "$_confirm" != "yes" ]]; then
            echo "Aborted."
            exit 1
        fi
        echo ""
    fi
fi

# ── Risk: wallet balance check ────────────────────────────────────────────────
if [[ "$RISK_LIMITS_ENABLED" == "1" ]]; then
    if command -v btcli &>/dev/null; then
        echo "Checking wallet balance..."
        _balance_raw=$(btcli wallet balance \
            --wallet.name "$COLDKEY" \
            --subtensor.network "$NETWORK" 2>/dev/null || true)

        _balance=$(echo "$_balance_raw" \
            | grep -oE 'τ\s*[0-9]+(\.[0-9]+)?' \
            | head -1 \
            | grep -oE '[0-9]+(\.[0-9]+)?' || echo "unknown")

        echo "  Coldkey balance: τ ${_balance}"

        if [[ "$_balance" != "unknown" ]]; then
            _below=$(awk -v bal="$_balance" -v min="$MIN_BALANCE_TAO" \
                'BEGIN { print (bal + 0 < min + 0) ? "yes" : "no" }')
            if [[ "$_below" == "yes" ]]; then
                echo ""
                echo "ERROR: Balance τ${_balance} is below MIN_BALANCE_TAO=${MIN_BALANCE_TAO}."
                echo "  Add TAO to your coldkey or lower MIN_BALANCE_TAO in $ENV_FILE."
                exit 1
            else
                echo "  ✓ Balance above minimum (τ${MIN_BALANCE_TAO})"
            fi
        else
            echo "  ⚠ Could not parse balance — skipping threshold check."
        fi
    else
        echo "  ⚠ btcli not found — skipping balance check."
    fi
else
    echo "  Risk limits disabled (RISK_LIMITS_ENABLED=0) — skipping balance check."
fi

# ── Precog repo check ─────────────────────────────────────────────────────────
if [[ ! -d "$PRECOG_DIR" ]]; then
    echo ""
    echo "ERROR: Precog repo not found at $PRECOG_DIR"
    echo "  Run deploy.sh first."
    exit 1
fi

# ── Activate venv ─────────────────────────────────────────────────────────────
_VENV="$PRECOG_DIR/.venv"
if [[ -f "$_VENV/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$_VENV/bin/activate"
    echo "  ✓ Activated venv: $_VENV"
else
    echo "  ⚠ No venv found at $_VENV — using system python3"
fi

# ── Stop any existing pm2 process ────────────────────────────────────────────
# Always delete (not restart) so the new run gets its own timestamped log files.
if pm2 describe "$MINER_NAME" &>/dev/null; then
    echo "  Stopping existing pm2 process '$MINER_NAME'..."
    pm2 delete "$MINER_NAME" 2>/dev/null || true
fi

# ── Start miner ───────────────────────────────────────────────────────────────
echo ""
echo "All checks passed. Starting miner..."
echo "  stdout → $OUT_LOG"
echo "  stderr → $ERR_LOG"
echo ""

cd "$PRECOG_DIR"
exec pm2 start \
    --name "$MINER_NAME" \
    --output "$OUT_LOG" \
    --error  "$OUT_LOG" \
    --log-date-format "YYYY-MM-DDTHH:mm:ss.SSS" \
    --merge-logs \
    --no-autorestart \
    "$_VENV/bin/python3" -- -u precog/miners/miner.py \
        --neuron.name     "$MINER_NAME" \
        --wallet.name     "$COLDKEY" \
        --wallet.hotkey   "$MINER_HOTKEY" \
        --subtensor.chain_endpoint "$_CHAIN" \
        --axon.port       "$MINER_PORT" \
        --netuid          "$_NETUID" \
        --logging.level   "$LOGGING_LEVEL" \
        "$_BT_LOG_FLAG" \
        --timeout         "$TIMEOUT" \
        --vpermit_tao_limit "$VPERMIT_TAO_LIMIT" \
        --forward_function "$FORWARD_FUNCTION"
