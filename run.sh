#!/bin/bash

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

if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Installing Orange App..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    echo "Install complete!"
    
    echo ""
    read -p "Do you want to download the default workflow models for ComfyUI now? (y/n): " DOWNLOAD_MODELS
    if [ "$DOWNLOAD_MODELS" = "y" ] || [ "$DOWNLOAD_MODELS" = "Y" ]; then
        python scripts/download_models.py
    fi
else
    source venv/bin/activate
fi

echo "Starting Orange App on port 7070..."
uvicorn app.main:app --host 0.0.0.0 --port 7070
