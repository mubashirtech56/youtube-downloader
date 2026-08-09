@echo off
REM ===========================================================================
REM Build the Windows .exe for YouTube Downloader Pro.
REM Run this ON WINDOWS (PyInstaller cannot cross-compile from Linux).
REM
REM   build\build_windows.bat
REM
REM Produces:  dist\youtube-downloader.exe
REM ===========================================================================
setlocal EnableDelayedExpansion

set APP_NAME=youtube-downloader

if exist venv\Scripts\python.exe (
    set PY=venv\Scripts\python.exe
) else if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
) else (
    set PY=python
)

echo [win] using python:   !PY!

REM ---- 1. Install dependencies ---------------------------------------------
echo [win] installing dependencies...
!PY! -m pip install --quiet --upgrade -r requirements.txt
if errorlevel 1 goto :fail

REM ---- 2. Generate application icons ----------------------------------------
echo [win] generating icons...
!PY! build\make_icons.py
if errorlevel 1 goto :fail

REM ---- 3. Fetch the bundled Deno JS runtime (YouTube n-challenge solving) ----
if not exist deno\deno.exe (
    echo [win] downloading Deno JS runtime (~90 MB)...
    !PY! build\fetch_deno.py
    if errorlevel 1 goto :fail
)

REM ---- 4. Build the .exe -----------------------------------------------------
echo [win] building dist\%APP_NAME%.exe (this can take a few minutes)...
!PY! -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyi-build youtube-downloader.spec
if errorlevel 1 goto :fail

echo.
echo [win] DONE - see: dist\%APP_NAME%.exe
pause
exit /b 0

:fail
echo.
echo [win] BUILD FAILED
pause
exit /b 1