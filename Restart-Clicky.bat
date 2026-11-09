@echo off
rem Restarts Clicky so it picks up the latest code in this folder (Python reads the code only when it starts).
rem Double-click it after merging changes; the tray's "Version" line then shows the commit now running.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*-m clicky*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
rem Give Windows a moment to let go of the old copy before starting the new one.
timeout /t 2 /nobreak >nul
call "%~dp0Clicky.bat"
