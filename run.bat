@echo off
REM run.bat — LiteLLM Configurator Launcher
REM Usage:
REM   run.bat gui          Launch the PySide6 GUI
REM   run.bat [args...]   Launch the CLI selector (passes args through)
REM   run.bat              Launch the CLI selector (default)

setlocal

REM Find a working Python executable (tries python, python3, py in order)
set PYTHON=
for %%P in (python python3 py) do (
    if not defined PYTHON (
        %%P --version >nul 2>&1 && set PYTHON=%%P
    )
)

if not defined PYTHON (
    echo ERROR: Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

if /i "%1"=="gui" (
    %PYTHON% "%~dp0start-litellm-gui.py"
) else (
    %PYTHON% "%~dp0start-litellm-select.py" %*
)
endlocal
