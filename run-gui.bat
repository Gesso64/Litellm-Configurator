@echo off
REM run-gui.bat — Launch the LiteLLM Configurator PySide6 GUI
REM Double-click this file to open the GUI directly.

setlocal
cd /d "%~dp0"

REM Use or create project-local virtual environment
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create venv. Make sure Python 3.10+ is installed.
        pause
        exit /b 1
    )
    echo [setup] Installing dependencies into .venv...
    call .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: pip install failed.
        pause
        exit /b 1
    )
    echo [setup] Done.
)

set "PATH=%~dp0.venv\Scripts;%PATH%"

"%~dp0.venv\Scripts\python.exe" "%~dp0start-litellm-gui.py"
endlocal
