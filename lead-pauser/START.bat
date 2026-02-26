@echo off
echo.
echo  ========================================
echo    BCI Lead Pauser - Local Worker
echo  ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Install dependencies if needed
if not exist ".installed" (
    echo  Installing dependencies...
    pip install -r requirements.txt
    playwright install chromium
    echo done > .installed
    echo  Dependencies installed!
    echo.
)

REM Run the worker
python worker.py
pause
