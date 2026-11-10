@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating project virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Could not create Python 3.12 environment.
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

if exist "requirements-lock.txt" (
    echo Installing exact pinned dependencies from requirements-lock.txt...
    ".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
) else (
    echo Lockfile missing. Installing base requirements...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1

    echo Creating initial dependency lockfile...
    ".venv\Scripts\python.exe" -m pip freeze > requirements-lock.txt
)

if errorlevel 1 exit /b 1

echo Checking dependency consistency...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1

echo Validating channel configuration...
".venv\Scripts\python.exe" app\foundation_v1.py validate-config
if errorlevel 1 exit /b 1

echo Running automated tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 exit /b 1

echo.
echo PHASE 1 ENVIRONMENT SETUP AND TESTS PASSED.
exit /b 0
