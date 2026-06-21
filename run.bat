@echo off
REM run.bat — LiteLLM Configurator Launcher (venv-based)
REM Usage:
REM   run.bat gui          Launch the PySide6 GUI
REM   run.bat [args...]   Launch the CLI selector (passes args through)
REM   run.bat              Launch the CLI selector (default)

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
        echo ERROR: pip install failed. Check requirements.txt.
        pause
        exit /b 1
    )
    echo [setup] Done.
)

REM Add venv Scripts to PATH so subprocess can find litellm.exe
set "PATH=%~dp0.venv\Scripts;%PATH%"

REM Use venv Python
set PYTHON=%~dp0.venv\Scripts\python.exe

if /i "%1"=="gui" (
    "%PYTHON%" "%~dp0start-litellm-gui.py"
) else (
    "%PYTHON%" "%~dp0start-litellm-select.py" %*
)
endlocal
