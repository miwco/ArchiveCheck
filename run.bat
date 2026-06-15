@echo off
REM ArchiveCheck launcher. Double-click to pick a folder, or drag a file/folder
REM onto it, or run from a terminal:  run.bat <file-or-folder> [options]
setlocal
cd /d "%~dp0"

if not "%~1"=="" (
    py -m archivecheck %*
    goto :open
)

REM No argument: show a folder picker.
for /f "usebackq delims=" %%F in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Choose a folder of videos to check'; if($d.ShowDialog() -eq 'OK'){ $d.SelectedPath }"`) do set "TARGET=%%F"

if not defined TARGET (
    echo No folder selected.
    pause
    exit /b 1
)

py -m archivecheck "%TARGET%"

:open
if exist "%~dp0vc_output" start "" "%~dp0vc_output"
echo.
echo Done. Output is in: %~dp0vc_output
pause
