@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-windows.ps1" %*
set "meetingbot_exit=%errorlevel%"
if not "%meetingbot_exit%"=="0" echo Meetingbot installation failed. See the error above.
pause
exit /b %meetingbot_exit%
