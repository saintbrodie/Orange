@echo off

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in your PATH.
    echo Downloading and installing Python 3.12 silently...
    curl -LO https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe
    start /wait python-3.12.3-amd64.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del python-3.12.3-amd64.exe
    echo.
    echo Python installation complete!
    echo Please close this window and run run.bat again to apply the new PATH variables.
    pause
    exit /b
)

set "FRESH_INSTALL=0"
if not exist "venv" (
    echo Virtual environment not found. Installing Orange App...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    echo Install complete!
    set "FRESH_INSTALL=1"
) else (
    call venv\Scripts\activate.bat
)

if "%FRESH_INSTALL%"=="0" goto skip_download
echo.
set /p "DOWNLOAD_MODELS=Do you want to download the default workflow models for ComfyUI now? (y/n): "
if /i "%DOWNLOAD_MODELS%"=="y" (
    python scripts\download_models.py
)
:skip_download

:loop
echo Starting Orange App on port 7070...
uvicorn app.main:app --host 0.0.0.0 --port 7070

if exist "RESTART_REQUIRED" (
    echo Restart requested...
    del "RESTART_REQUIRED"
    timeout /t 2 >nul
    goto loop
)
