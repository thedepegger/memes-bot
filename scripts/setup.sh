#!/usr/bin/env bash
# One-shot bootstrap for the crypto meme bot.
# Idempotent: safe to re-run.

set -e

# Move to project root (this script lives in scripts/)
cd "$(dirname "$0")/.."

echo "==> Looking for Python 3.11+..."
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON_BIN="$candidate"
            echo "    Using Python $version ($candidate)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "ERROR: Python 3.11+ not found on your PATH."
    echo ""
    echo "Install it first:"
    echo "  macOS:        brew install python@3.11"
    echo "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "  Other:        download from python.org/downloads"
    echo ""
    exit 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
    echo "==> Creating .venv/"
    "$PYTHON_BIN" -m venv .venv
else
    echo "==> .venv/ already exists, skipping creation"
fi

# Upgrade pip + install deps
echo "==> Installing dependencies (this takes ~30s)..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "    done"

# Scaffold .env from template
if [ ! -f ".env" ]; then
    echo "==> Creating .env from .env.example"
    cp .env.example .env
    SCAFFOLDED_ENV=1
else
    echo "==> .env already exists, leaving alone"
    SCAFFOLDED_ENV=0
fi

# Make sure data/ and logs/ exist
mkdir -p data logs

echo ""
echo "============================================================"
echo "  setup complete"
echo "============================================================"

if [ "$SCAFFOLDED_ENV" = "1" ]; then
    echo ""
    echo "  NEXT: open .env in your editor and fill in your API keys."
    echo "  See docs/SETUP.md §3 for where to get each one (~10 min)."
fi

echo ""
echo "  Then verify:"
echo "    make dry-run    # smoke test the pipeline (no Telegram, no X)"
echo "    make test       # run the test suite"
echo ""
echo "  And when you're ready:"
echo "    make run        # start the bot for real"
echo ""
