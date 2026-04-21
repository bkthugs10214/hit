#!/usr/bin/env bash
# run_miner.sh — pre-flight safety wrapper around "make miner"
#
# Usage:
#   ./run_miner.sh                     # prompts for confirmation if NETWORK=finney
#   ./run_miner.sh --make_it_rain      # skips mainnet confirmation, no prompts
#
# Environment:
#   PRECOG_DIR   path to the Precog subnet repo (default: ~/precog)
#   ENV_FILE     path to the .env.miner file (default: $PRECOG_DIR/.env.miner)
#
# Risk controls read from ENV_FILE:
#   NETWORK              testnet | finney  (default: testnet)
#   RISK_LIMITS_ENABLED  1 | 0             (default: 1)
#   MIN_BALANCE_TAO      float             (default: 1.0)
#   COLDKEY              wallet coldkey name
#   MINER_HOTKEY         wallet hotkey name

set -euo pipefail

# ── Parse flags ───────────────────────────────────────────────────────────────
MAKE_IT_RAIN=false
for arg in "$@"; do
    [[ "$arg" == "--make_it_rain" ]] && MAKE_IT_RAIN=true
done

# ── Locate env file ───────────────────────────────────────────────────────────
PRECOG_DIR="${PRECOG_DIR:-$HOME/precog}"
ENV_FILE="${ENV_FILE:-$PRECOG_DIR/.env.miner}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: env file not found: $ENV_FILE"
    echo "  Run deploy.sh first, then edit $ENV_FILE"
    exit 1
fi

# Load env vars (skip comment lines and blank lines)
set -a
# shellcheck disable=SC1090
source <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$')
set +a

# ── Defaults for risk vars (may not be in older env files) ───────────────────
NETWORK="${NETWORK:-testnet}"
RISK_LIMITS_ENABLED="${RISK_LIMITS_ENABLED:-1}"
MIN_BALANCE_TAO="${MIN_BALANCE_TAO:-1.0}"
COLDKEY="${COLDKEY:-miner}"
MINER_HOTKEY="${MINER_HOTKEY:-default}"

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Precog Baseline Miner — Pre-flight Check        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Network     : $NETWORK"
echo "  Coldkey     : $COLDKEY"
echo "  Hotkey      : $MINER_HOTKEY"
echo "  Risk limits : $RISK_LIMITS_ENABLED"
echo "  Min balance : ${MIN_BALANCE_TAO} τ"
echo "  Make it rain: $MAKE_IT_RAIN"
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
        # Fetch raw balance output and extract the τ value
        _balance_raw=$(btcli wallet balance \
            --wallet.name "$COLDKEY" \
            --subtensor.network "$NETWORK" 2>/dev/null || true)

        # Parse the first τ value from the output (handles both old and new btcli formats)
        _balance=$(echo "$_balance_raw" \
            | grep -oE 'τ\s*[0-9]+(\.[0-9]+)?' \
            | head -1 \
            | grep -oE '[0-9]+(\.[0-9]+)?' || echo "unknown")

        echo "  Coldkey balance: τ ${_balance}"

        if [[ "$_balance" != "unknown" ]]; then
            # awk comparison: fail if balance < MIN_BALANCE_TAO
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
        echo "    Install with: pip install bittensor-cli"
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

if [[ ! -f "$PRECOG_DIR/Makefile" ]]; then
    echo ""
    echo "ERROR: No Makefile found in $PRECOG_DIR — deploy may be incomplete."
    echo "  Re-run deploy.sh."
    exit 1
fi

# ── Start miner ───────────────────────────────────────────────────────────────
echo ""
echo "All checks passed. Starting miner..."
echo "  cd $PRECOG_DIR && make miner ENV_FILE=$ENV_FILE"
echo ""

cd "$PRECOG_DIR"
exec make miner ENV_FILE="$ENV_FILE"
