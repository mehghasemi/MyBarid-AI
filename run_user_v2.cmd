@echo off
setlocal EnableExtensions

cd /d "%~dp0"
title CRM Quality Reviewer - User Mode

echo ============================================
echo   CRM Quality Reviewer - User Mode
 echo ============================================
echo.
echo This launcher runs WITHOUT Administrator rights.
echo.

where python >nul 2>&1
if errorlevel 1 goto :NO_PYTHON

echo [1/4] Python detected:
python --version
if errorlevel 1 goto :PYTHON_ERROR

set "VENV_DIR=%~dp0.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" goto :CREATE_VENV

echo [2/4] Using existing local virtual environment.
goto :INSTALL

:CREATE_VENV
echo [2/4] Creating local virtual environment...
python -m venv "%VENV_DIR%"
if errorlevel 1 goto :VENV_ERROR
if not exist "%PYTHON_EXE%" goto :VENV_ERROR

echo Local virtual environment created successfully.

:INSTALL
echo.
echo [3/4] Checking/installing required packages...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :PIP_ERROR

echo.
echo [4/4] Starting application...
echo.
"%PYTHON_EXE%" main.py
set "APP_EXIT_CODE=%errorlevel%"

echo.
if "%APP_EXIT_CODE%"=="0" (
    echo Application closed normally.
) else (
    echo [ERROR] Application exited with code %APP_EXIT_CODE%.
)
echo.
pause
exit /b %APP_EXIT_CODE%

:NO_PYTHON
echo [ERROR] Python was not found in PATH.
echo Please install Python 3.10 or later and enable "Add Python to PATH".
goto :FAIL

:PYTHON_ERROR
echo [ERROR] Python was found but could not be started.
goto :FAIL

:VENV_ERROR
echo [ERROR] Could not create the local Python virtual environment.
echo Make sure this application folder is writable by your Windows user.
goto :FAIL

:PIP_ERROR
echo [ERROR] Required Python packages could not be installed.
echo Check the internet connection and requirements.txt.
goto :FAIL

:FAIL
echo.
pause
exit /b 1
