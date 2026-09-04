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
    echo "Virtual environment not found. Installing Orange App..."
    python3 -m venv venv
    FRESH_INSTALL=1
fi

source venv/bin/activate

# Re-sync dependencies after an Orange update changes requirements.txt.
REQ_HASH=$(python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")
REQ_HASH_FILE="venv/.orange-requirements.sha256"
OLD_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
    OLD_HASH=$(cat "$REQ_HASH_FILE")
fi

if [ "$FRESH_INSTALL" = "1" ] || [ "$REQ_HASH" != "$OLD_HASH" ]; then
    echo "Installing/updating Orange dependencies..."
    python -m pip install -r requirements.txt
    printf '%s' "$REQ_HASH" > "$REQ_HASH_FILE"
    echo "Dependency sync complete!"
fi

if [ "$FRESH_INSTALL" = "1" ]; then
    echo ""
    read -p "Do you want to download the default workflow models for ComfyUI now? (y/n): " DOWNLOAD_MODELS
    if [ "$DOWNLOAD_MODELS" = "y" ] || [ "$DOWNLOAD_MODELS" = "Y" ]; then
        python scripts/download_models.py
    fi
fi

while true; do
    rm -f RESTART_REQUIRED
    echo "Starting Orange App on port 7070..."
    uvicorn app.main:app --host 0.0.0.0 --port 7070

    if [ -f "RESTART_REQUIRED" ]; then
        echo "Restart requested..."
        rm -f RESTART_REQUIRED
        sleep 2
        continue
    fi

    break
done
