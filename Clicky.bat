@echo off
rem Starts Clicky without a console window. Put a shortcut to this file in shell:startup to launch at login.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Clicky isn't installed yet. See README.md, step 2.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m clicky
