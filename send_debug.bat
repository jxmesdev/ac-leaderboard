@echo off
rem One-click: snapshot the app's debug log (and live-setup capture state)
rem and push it to GitHub so it can be read remotely. Run from the app folder.
cd /d "%~dp0"
echo === debug.log ===================================== > debug_report.txt
type debug.log >> debug_report.txt 2>nul
echo. >> debug_report.txt
echo === current_setup.ini (live capture) ============== >> debug_report.txt
type current_setup.ini >> debug_report.txt 2>nul
git add debug_report.txt
git commit -m "debug report from rig"
git pull --rebase
git push
echo.
echo Debug report pushed. You can close this window.
pause
