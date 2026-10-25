@echo off
rem Starts the Demand & Supply Zone Scanner at http://127.0.0.1:8000
rem Double-click this file. Press Ctrl+C in this window to stop the server.
title Zone Scanner
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating the Python environment...
    python -m venv .venv || goto :error
    ".venv\Scripts\python" -m pip install -r requirements.txt || goto :error
)

if not exist ".env" (
    echo No .env found - copying .env.example. Edit .env to add your settings.
    copy .env.example .env >nul
)

rem Open the browser a few seconds after the server starts
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"

echo Starting server at http://127.0.0.1:8000  (Ctrl+C to stop)
".venv\Scripts\python" -m uvicorn app.main:app --reload
if errorlevel 1 (
    echo.
    echo Server stopped with an error. If it says the address is in use, the app is
    echo already running in another window - close that one first.
    pause
)
goto :eof

:error
echo.
echo Setup failed. Make sure Python 3.10+ is installed and on PATH.
pause
