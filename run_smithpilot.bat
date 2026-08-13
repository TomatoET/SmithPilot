@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
)

"%PYTHON_EXE%" main.py
if errorlevel 1 (
    echo.
    echo SmithPilot exited with an error.
    echo Install dependencies with:
    echo pip install -r requirements.txt
    echo.
    pause
)

endlocal
