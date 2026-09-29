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
    echo Python installation complete.
    echo Please close this window and run run.bat again to apply the new PATH variables.
    pause
    exit /b
)

set "FRESH_INSTALL=0"
if not exist "venv" (
    echo Creating Orange environment...
    python -m venv venv
    if errorlevel 1 exit /b 1
    set "FRESH_INSTALL=1"
)

call venv\Scripts\activate.bat
if errorlevel 1 exit /b 1
set "PYTHONUTF8=1"

rem Re-sync dependencies whenever requirements.txt changes after an update.
for /f %%H in ('python -c "import hashlib; print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())"') do set "REQ_HASH=%%H"
set "OLD_HASH="
if exist "venv\.orange-requirements.sha256" set /p OLD_HASH=<"venv\.orange-requirements.sha256"

if "%FRESH_INSTALL%"=="1" goto install_deps
if not "%REQ_HASH%"=="%OLD_HASH%" goto install_deps
goto deps_done

:install_deps
echo Syncing Orange dependencies...
python -m pip install --disable-pip-version-check --quiet -r requirements.txt
if errorlevel 1 exit /b 1
>"venv\.orange-requirements.sha256" echo(!REQ_HASH!
echo Dependencies ready.

:deps_done
if "%FRESH_INSTALL%"=="1" echo Fresh install: finish setup in the Orange browser wizard.

python scripts\run_orange.py
exit /b %errorlevel%
