@echo off
if not exist "venv" (
    echo Virtual environment not found. Installing Orange App...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    echo Install complete!
) else (
    call venv\Scripts\activate.bat
)

echo Starting Orange App on port 7070...
uvicorn main:app --host 0.0.0.0 --port 7070
