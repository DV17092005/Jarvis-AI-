@echo off
setlocal

echo.
echo ============================================
echo          JARVIS AI ASSISTANT SETUP
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 or newer was not found in PATH.
    echo Install Python from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo Starting Jarvis at http://127.0.0.1:8765
echo Press Ctrl+C in this window to stop.
echo.
".venv\Scripts\python.exe" jarvis_server.py
if errorlevel 1 (
    echo Jarvis stopped with an error. See the message above.
    pause
    exit /b 1
)
