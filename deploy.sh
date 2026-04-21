#!/usr/bin/env bash
# deploy.sh — wires precog-baseline-miner into the Precog subnet repo
#
# Usage:
#   ./deploy.sh                                # clones Precog to ~/precog-node
#   PRECOG_DIR=/path/to/precog ./deploy.sh     # use an existing Precog clone
#
# After running this script:
#   1. Edit $PRECOG_DIR/.env.miner with your wallet credentials
#   2. ./run_miner.sh   (pre-flight checks then starts the miner)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRECOG_REPO="https://github.com/coinmetrics/precog"
# Default to ~/precog-node to avoid collision with the ~/precog workspace dir
PRECOG_DIR="${PRECOG_DIR:-$HOME/precog-node}"
FORWARD_MODULE="baseline_miner"
VENV_DIR="$PRECOG_DIR/.venv"
# Pinned btcli version — bump here when upgrading, run_miner.sh verifies this
BTCLI_VERSION="9.20.1"

echo "=== Precog Baseline Miner Deployment ==="
echo "  Precog dir  : $PRECOG_DIR"
echo "  Venv        : $VENV_DIR"
echo "  Our src     : $SCRIPT_DIR"
echo "  btcli target: $BTCLI_VERSION"
echo ""

# ── Step 0: Install / verify btcli via pipx ──────────────────────────────────
echo "[0/6] Checking btcli..."
if ! command -v pipx &>/dev/null; then
    echo "      pipx not found — installing..."
    pip3 install pipx --break-system-packages -q || python3 -m pip install pipx --user -q
    export PATH="$HOME/.local/bin:$PATH"
fi

_installed_btcli_ver=""
if command -v btcli &>/dev/null; then
    _installed_btcli_ver=$(btcli --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
fi

if [[ "$_installed_btcli_ver" == "$BTCLI_VERSION" ]]; then
    echo "      btcli $BTCLI_VERSION already installed — skipping."
else
    echo "      Installing bittensor-cli==$BTCLI_VERSION via pipx..."
    pipx install "bittensor-cli==$BTCLI_VERSION" --force -q
    export PATH="$HOME/.local/bin:$PATH"
    echo "      btcli $BTCLI_VERSION installed."
fi

# ── Step 1: Clone Precog repo if not present ─────────────────────────────────
if [ ! -f "$PRECOG_DIR/pyproject.toml" ] && [ ! -f "$PRECOG_DIR/setup.py" ]; then
    echo "[1/7] Cloning Precog repo..."
    git clone "$PRECOG_REPO" "$PRECOG_DIR"
else
    echo "[1/7] Precog repo found at $PRECOG_DIR — skipping clone."
fi

# ── Step 2: Create venv if not present ───────────────────────────────────────
echo "[2/7] Setting up virtual environment..."
if [ ! -f "$VENV_DIR/bin/python" ]; then
    # Prefer Python 3.11 — bittensor works best on 3.9–3.11
    if command -v python3.11 &>/dev/null; then
        python3.11 -m venv "$VENV_DIR"
        echo "      Created venv with Python 3.11"
    else
        python3 -m venv "$VENV_DIR"
        echo "      Created venv with $(python3 --version)"
    fi
else
    echo "      Venv already exists — skipping."
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

# ── Step 3: Install Precog dependencies ──────────────────────────────────────
echo "[3/7] Installing Precog dependencies..."
cd "$PRECOG_DIR"
if command -v poetry &>/dev/null && [ -f "poetry.lock" ]; then
    POETRY_VIRTUALENVS_IN_PROJECT=false poetry install --no-interaction
else
    "$PIP" install -e . --quiet
fi
cd "$SCRIPT_DIR"

# ── Step 4: Install our package into the same venv ───────────────────────────
echo "[4/7] Installing precog-baseline-miner..."
"$PIP" install -e "$SCRIPT_DIR" --quiet

# ── Step 5: Copy our forward function into the Precog miners directory ────────
MINERS_DIR="$PRECOG_DIR/precog/miners"
if [ ! -d "$MINERS_DIR" ]; then
    echo "ERROR: $MINERS_DIR not found — is $PRECOG_DIR a valid Precog clone?"
    exit 1
fi
DEST="$MINERS_DIR/${FORWARD_MODULE}.py"
echo "[5/7] Deploying forward function → $DEST"
cp "$SCRIPT_DIR/src/miner/forward_custom.py" "$DEST"

# ── Step 6: Copy env template if .env.miner doesn't exist ────────────────────
ENV_DEST="$PRECOG_DIR/.env.miner"
if [ ! -f "$ENV_DEST" ]; then
    echo "[6/7] Creating $ENV_DEST from template..."
    cp "$SCRIPT_DIR/.env.example" "$ENV_DEST"
    sed -i "s/^FORWARD_FUNCTION=.*/FORWARD_FUNCTION=${FORWARD_MODULE}/" "$ENV_DEST"
    echo "      Created $ENV_DEST — EDIT THIS FILE with your wallet credentials."
else
    echo "[6/7] $ENV_DEST already exists — not overwriting."
    echo "      Make sure FORWARD_FUNCTION=${FORWARD_MODULE} is set in it."
fi

# ── Step 7: Write pinned btcli version for run_miner.sh to verify ─────────────
echo "[7/7] Recording pinned btcli version..."
echo "$BTCLI_VERSION" > "$SCRIPT_DIR/.btcli-version"
echo "      Wrote $SCRIPT_DIR/.btcli-version"

echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "  1. Edit your wallet credentials in: $ENV_DEST"
echo "     Required: COLDKEY, MINER_HOTKEY, NETWORK"
echo ""
echo "  2. Create wallet keys (if not done yet):"
echo "     btcli wallet new_coldkey --wallet.name miner"
echo "     btcli wallet new_hotkey  --wallet.name miner --wallet.hotkey default"
echo ""
echo "  3. Register your hotkey on the Precog subnet:"
echo "     btcli s register --netuid <precog_netuid> --wallet.name miner --wallet.hotkey default"
echo ""
echo "  4. Open miner port (default 8092):"
echo "     sudo ufw allow 8092/tcp"
echo ""
echo "  5. Start the miner (with pre-flight safety checks):"
echo "     PRECOG_DIR=$PRECOG_DIR $SCRIPT_DIR/run_miner.sh"
echo ""
echo "  6. Watch for forecasts:"
echo "     tail -f ~/.precog_baseline/forecasts.jsonl"
