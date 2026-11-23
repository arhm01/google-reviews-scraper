@echo off
setlocal
rem Double-click this file to look up Google ratings for a Google Sheet tab (Windows).
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title Google Reviews lookup

rem ---- One-time setup: only runs the first time, or after the folder is copied to a new PC ----
if not exist ".venv\Scripts\python.exe" goto setup
".venv\Scripts\python.exe" -c "import playwright" >nul 2>nul
if not errorlevel 1 goto run

:setup
echo ==================================================
echo    Google Reviews lookup - first-time setup
echo ==================================================
echo.
echo This takes a few minutes and only happens once.
echo.
set "PY="
py -3 -c "print()" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto havepython
python -c "print()" >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY goto nopython

:havepython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython
if exist ".venv" rmdir /s /q ".venv"
%PY% -m venv .venv
if errorlevel 1 goto setupfail
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto setupfail
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto setupfail
echo.
echo Setup done.
echo.

:run
".venv\Scripts\python.exe" start.py
goto end

:nopython
echo Python isn't installed on this computer yet. To install it:
echo.
echo   1. Go to https://www.python.org/downloads/ and click the yellow Download button.
echo   2. Open the file you downloaded.
echo   3. On the first screen, tick the box "Add python.exe to PATH", then click "Install Now".
echo   4. When it says "Setup was successful", close it and double-click this file again.
goto end

:oldpython
echo The Python on this computer is too old. Install the latest version from
echo https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then double-click
echo this file again.
goto end

:setupfail
echo.
echo Setup didn't finish. Check your internet connection and try again.
goto end

:end
echo.
pause
