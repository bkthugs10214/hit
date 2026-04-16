#!/usr/bin/env bash
# deploy.sh — wires precog-baseline-miner into the Precog repo
#
# Usage:
#   ./deploy.sh                          # clones Precog to ~/precog
#   PRECOG_DIR=/path/to/precog ./deploy.sh   # use an existing Precog clone
#
# After running this script:
#   1. Edit $PRECOG_DIR/.env.miner with your wallet credentials
#   2. cd $PRECOG_DIR && make miner ENV_FILE=.env.miner

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRECOG_REPO="https://github.com/coinmetrics/precog"
PRECOG_DIR="${PRECOG_DIR:-$HOME/precog}"
FORWARD_MODULE="baseline_miner"

echo "=== Precog Baseline Miner Deployment ==="
echo "  Precog dir : $PRECOG_DIR"
echo "  Our src    : $SCRIPT_DIR"
echo ""

# ── Step 1: Clone Precog repo if not present ─────────────────────────────────
if [ ! -d "$PRECOG_DIR" ]; then
    echo "[1/5] Cloning Precog repo..."
    git clone "$PRECOG_REPO" "$PRECOG_DIR"
else
    echo "[1/5] Precog repo already exists at $PRECOG_DIR — skipping clone."
fi

# ── Step 2: Install Precog dependencies ──────────────────────────────────────
echo "[2/5] Installing Precog dependencies..."
cd "$PRECOG_DIR"
if command -v poetry &>/dev/null; then
    poetry install --no-interaction
else
    pip install -e . --quiet
fi
cd "$SCRIPT_DIR"

# ── Step 3: Install our package ──────────────────────────────────────────────
echo "[3/5] Installing precog-baseline-miner..."
pip install -e "$SCRIPT_DIR" --quiet

# ── Step 4: Copy our forward function into the Precog miners directory ────────
DEST="$PRECOG_DIR/precog/miners/${FORWARD_MODULE}.py"
echo "[4/5] Deploying forward function to $DEST"
cp "$SCRIPT_DIR/src/miner/forward_custom.py" "$DEST"
echo "      Copied src/miner/forward_custom.py → $DEST"

# ── Step 5: Copy env template if .env.miner doesn't exist ────────────────────
ENV_DEST="$PRECOG_DIR/.env.miner"
if [ ! -f "$ENV_DEST" ]; then
    echo "[5/5] Creating $ENV_DEST from template..."
    cp "$SCRIPT_DIR/.env.example" "$ENV_DEST"
    # Ensure FORWARD_FUNCTION points to our module
    sed -i "s/^FORWARD_FUNCTION=.*/FORWARD_FUNCTION=${FORWARD_MODULE}/" "$ENV_DEST"
    echo "      Created $ENV_DEST — EDIT THIS FILE with your wallet credentials."
else
    echo "[5/5] $ENV_DEST already exists — not overwriting."
    echo "      Make sure FORWARD_FUNCTION=${FORWARD_MODULE} is set in it."
fi

echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "  1. Edit your wallet credentials in: $ENV_DEST"
echo "     Required: COLDKEY, MINER_HOTKEY, NETWORK"
echo ""
echo "  2. Register your hotkey on the Precog subnet (if not already done):"
echo "     btcli s register --netuid <precog_netuid> --wallet.name <coldkey>"
echo ""
echo "  3. Open miner port (default 8092) for inbound TCP:"
echo "     sudo ufw allow 8092/tcp"
echo ""
echo "  4. Start the miner:"
echo "     cd $PRECOG_DIR && make miner ENV_FILE=.env.miner"
echo ""
echo "  5. Watch for forecasts:"
echo "     tail -f ~/.precog_baseline/forecasts.jsonl"
