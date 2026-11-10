@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Project environment missing. Run setup_project.bat first.
    exit /b 1
)

".venv\Scripts\python.exe" app\foundation_v1.py validate-config
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" app\youtube_universe_master_dashboard_v33.py
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" app\youtube_universe_final_audit_v33.py
exit /b %errorlevel%
