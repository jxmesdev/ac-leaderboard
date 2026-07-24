@echo off
rem One-click: snapshot the app's debug log (and live-setup capture state)
rem and push it to GitHub so it can be read remotely. Run from the app folder.
rem The filename is per-PC so two rigs never fight over the same file.
cd /d "%~dp0"
set REPORT=debug_report_%COMPUTERNAME%.txt
echo === debug.log ===================================== > %REPORT%
type debug.log >> %REPORT% 2>nul
echo. >> %REPORT%
echo === current_setup.ini (live capture) ============== >> %REPORT%
type current_setup.ini >> %REPORT% 2>nul
echo. >> %REPORT%
echo === git status (app folder) ======================= >> %REPORT%
git status --porcelain >> %REPORT% 2>nul
echo. >> %REPORT%
echo === AC log.txt tail (python import errors land here) >> %REPORT%
powershell -NoProfile -Command "Get-Content -Tail 300 \"$env:USERPROFILE\Documents\Assetto Corsa\logs\log.txt\"" >> %REPORT% 2>nul
git add %REPORT%
git commit -m "debug report from %COMPUTERNAME%"
git pull --rebase
if errorlevel 1 (
    echo Pull hit a conflict -- undoing so the app is not left stuck.
    git rebase --abort
)
git push
if errorlevel 1 (
    echo.
    echo PUSH FAILED -- the report is saved locally; try again later.
) else (
    echo.
    echo Debug report pushed. You can close this window.
)
pause
