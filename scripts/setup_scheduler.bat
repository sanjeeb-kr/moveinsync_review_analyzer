@echo off
REM ==============================================================================
REM MoveInSync Play Store Diagnosis - Windows Task Scheduler Setup
REM
REM WHAT THIS SCRIPT DOES:
REM 1. Registers a daily scheduled task in Windows Task Scheduler named "MoveInSync_Daily_Report".
REM 2. Runs once a day at 06:00 AM IST (configurable).
REM 3. Executes `run_report.py` using the project's virtual environment python.
REM 4. The task is created in a DISABLED (OFF) state by default to prevent accidental runs.
REM
REM TO ENABLE LATER:
REM   schtasks /Change /TN "MoveInSync_Daily_Report" /ENABLE
REM
REM TO DELETE:
REM   schtasks /Delete /TN "MoveInSync_Daily_Report" /F
REM ==============================================================================

set "PROJECT_DIR=%~dp0.."
set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "SCRIPT_PATH=%PROJECT_DIR%\run_report.py"

echo Checking paths...
echo Project Dir: %PROJECT_DIR%
echo Python:      %PYTHON_EXE%
echo Script:      %SCRIPT_PATH%

if not exist "%PYTHON_EXE%" (
    echo ERROR: Virtual environment python not found at %PYTHON_EXE%
    echo Please create the virtual environment first.
    exit /b 1
)

echo Registering Windows Scheduled Task 'MoveInSync_Daily_Report' (Disabled by default)...
schtasks /Create /TN "MoveInSync_Daily_Report" /TR "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" /SC DAILY /ST 06:00 /F
if %errorlevel% neq 0 (
    echo Failed to create scheduled task. Try running Command Prompt as Administrator.
    exit /b %errorlevel%
)

echo Disabling task by default (off by default)...
schtasks /Change /TN "MoveInSync_Daily_Report" /DISABLE

echo.
echo ==============================================================================
echo SUCCESS: 'MoveInSync_Daily_Report' created successfully in Task Scheduler!
echo Status: DISABLED (OFF BY DEFAULT)
echo To enable: schtasks /Change /TN "MoveInSync_Daily_Report" /ENABLE
echo ==============================================================================
pause
