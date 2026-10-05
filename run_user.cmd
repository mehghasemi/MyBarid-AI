@echo off
setlocal EnableExtensions

title CRM Quality Reviewer - User Mode
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo ============================================
echo   CRM Quality Reviewer - User Mode
echo ============================================
echo.
echo This launcher does NOT request Administrator rights.
echo.

:: ---------------------------------------------------------------
:: 1. Check that Python is available.
:: ---------------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on this system.
    echo.
    echo Please install Python 3.10 or later and enable:
    echo   "Add python.exe to PATH"
    echo.
    echo After installation, run this file again.
    pause
    exit /b 1
)

echo [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo [ERROR] Python could not be started.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------
:: 2. Create an application-local virtual environment.
::    This avoids installing packages into the system Python and
::    therefore avoids the need for Administrator rights.
:: ---------------------------------------------------------------
if not exist "%PYTHON_EXE%" (
    echo.
    echo [2/4] Creating application virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo [ERROR] Could not create the local Python virtual environment.
        echo.
        echo The application folder must be writable by your Windows user.
        echo If this is a company-managed folder with restricted permissions,
        echo move the application to a folder where you have write access.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Local virtual environment already exists.
)

:: ---------------------------------------------------------------
:: 3. Install/update application dependencies inside .venv only.
::    No system-wide pip operation is performed.
:: ---------------------------------------------------------------
echo.
echo [3/4] Checking required packages...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Required packages could not be installed.
    echo Check your internet connection or package access policy,
    echo then run this file again.
    echo.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------
:: 4. Start the application with the normal Windows user token.
:: ---------------------------------------------------------------
echo.
echo [4/4] Starting the application...
echo.
"%PYTHON_EXE%" main.py

set "APP_EXIT_CODE=%errorlevel%"
echo.
echo The application has closed. Exit code: %APP_EXIT_CODE%
pause
exit /b %APP_EXIT_CODE%
