#!/bin/bash
set -e

cd "$(dirname "$0")"

if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Attempting to install..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v yum &> /dev/null; then
        sudo yum install -y python3 python3-pip
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm python python-pip
    elif command -v brew &> /dev/null; then
        brew install python
    else
        echo "Could not detect a package manager. Please install Python 3 manually."
        exit 1
    fi
fi

FRESH_INSTALL=0
if [ ! -d "venv" ]; then
    echo "Creating Orange environment..."
    python3 -m venv venv
    FRESH_INSTALL=1
fi

source venv/bin/activate
export PYTHONUTF8=1

# Re-sync dependencies after an Orange update changes requirements.txt.
REQ_HASH=$(python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")
REQ_HASH_FILE="venv/.orange-requirements.sha256"
OLD_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
    OLD_HASH=$(cat "$REQ_HASH_FILE")
fi

if [ "$FRESH_INSTALL" = "1" ] || [ "$REQ_HASH" != "$OLD_HASH" ]; then
    echo "Syncing Orange dependencies..."
    python -m pip install --disable-pip-version-check --quiet -r requirements.txt
    printf '%s\n' "$REQ_HASH" > "$REQ_HASH_FILE"
    echo "Dependencies ready."
fi

if [ "$FRESH_INSTALL" = "1" ]; then
    echo "Fresh install: finish setup in the Orange browser wizard."
fi

exec python scripts/run_orange.py
