@echo off
rem Weekly zone journal: saves last week's 2h zones and checks all earlier ones.
rem Scheduled every Saturday by Windows Task Scheduler (see README); can also be double-clicked.
rem Output is appended to journal.log in this folder.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing - run start.bat once first. >> journal.log
    exit /b 1
)
".venv\Scripts\python" -m app.journal >> journal.log 2>&1
