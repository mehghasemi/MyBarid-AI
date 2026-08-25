@echo off
setlocal EnableExtensions

title CRM Quality Reviewer
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo ============================================
echo   CRM Quality Reviewer
echo ============================================
echo.
echo Running in user mode. Administrator rights are not required.
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on this system.
    echo Please install Python 3.10 or later and enable:
    echo   "Add python.exe to PATH"
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [1/3] Creating application-local virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Could not create the local virtual environment.
        echo Make sure this folder is writable by your Windows user.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Application-local virtual environment already exists.
)

echo.
echo [2/3] Installing required packages for the current user...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Required packages could not be installed.
    echo Check your internet connection or package access policy.
    pause
    exit /b 1
)

echo.
echo [3/3] Starting the application...
"%PYTHON_EXE%" main.py

set "APP_EXIT_CODE=%errorlevel%"
echo.
echo The application has closed. Exit code: %APP_EXIT_CODE%
pause
exit /b %APP_EXIT_CODE%
