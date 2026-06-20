@echo off
REM run-gui.bat — Launch the LiteLLM Configurator PySide6 GUI
REM Double-click this file to open the GUI directly.

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

%PYTHON% "%~dp0start-litellm-gui.py"
endlocal
