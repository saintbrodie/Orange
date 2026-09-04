@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

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
    set "FRESH_INSTALL=1"
)

call venv\Scripts\activate.bat

rem Re-sync dependencies whenever requirements.txt changes after an update.
for /f %%H in ('python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())"') do set "REQ_HASH=%%H"
set "OLD_HASH="
if exist "venv\.orange-requirements.sha256" set /p OLD_HASH=<"venv\.orange-requirements.sha256"

if "%FRESH_INSTALL%"=="1" goto install_deps
if not "%REQ_HASH%"=="%OLD_HASH%" goto install_deps
goto deps_done

:install_deps
echo Installing/updating Orange dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
>"venv\.orange-requirements.sha256" echo|set /p="%REQ_HASH%"
echo Dependency sync complete!

:deps_done
if "%FRESH_INSTALL%"=="0" goto skip_download
echo.
set /p "DOWNLOAD_MODELS=Do you want to download the default workflow models for ComfyUI now? (y/n): "
if /i "%DOWNLOAD_MODELS%"=="y" (
    python scripts\download_models.py
)
:skip_download

:loop
if exist "RESTART_REQUIRED" del "RESTART_REQUIRED"
echo Starting Orange App on port 7070...
uvicorn app.main:app --host 0.0.0.0 --port 7070

if exist "RESTART_REQUIRED" (
    echo Restart requested...
    del "RESTART_REQUIRED"
    timeout /t 2 >nul
    goto loop
)
