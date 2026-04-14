#!/bin/bash
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Installing Orange App..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    echo "Install complete!"
else
    source venv/bin/activate
fi

echo "Starting Orange App on port 7070..."
uvicorn main:app --host 0.0.0.0 --port 7070
