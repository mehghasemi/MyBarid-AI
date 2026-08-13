@echo off
setlocal
title CRM Quality Reviewer

:: ------------------------------------------------------------------
:: Self-elevate: on some Windows systems, even an Administrator-group
:: user runs with a filtered (non-elevated) token unless the process
:: explicitly requests elevation. A known interaction bug between
:: pywebview/WebView2 and Windows Accessibility (UI Automation) can
:: cause the app to hang on startup when NOT elevated. Requesting
:: elevation here avoids that problem automatically.
:: ------------------------------------------------------------------
net session >nul 2>&1
if not %errorLevel% == 0 (
    echo This app needs to run with Administrator rights on this system
    echo to avoid a known Windows Accessibility/WebView2 startup issue.
    echo A User Account Control prompt will appear - please click Yes.
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo ============================================
echo   CRM Quality Reviewer - Setup and Run
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on this system.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    echo During installation, make sure to check the box "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking Python version...
python --version

echo.
echo [2/3] Installing required packages (openpyxl, pywebview)...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed. Check your internet connection,
    echo then run this file again. If the problem continues, run this command
    echo manually and read the error message:
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting the application...
echo (If a window does not appear within a few seconds, check the messages below.)
echo.
python main.py

echo.
echo The application has closed.
pause
