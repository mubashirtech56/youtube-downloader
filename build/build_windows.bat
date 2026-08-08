@echo off
REM ===========================================================================
REM Build a Windows .exe for the YouTube Downloader desktop app.
REM Run this ON WINDOWS (inside the project folder, with the venv active or
REM using the right python). PyInstaller cannot cross-compile from Linux.
REM
REM   build\build_windows.bat
REM
REM Produces:  dist\youtube-downloader.exe
REM
REM The .exe bundles main.py (CustomTkinter + yt-dlp), the YouTube icon, and a
REM native C++ splash launcher (splash\launcher_win.exe) so startup feels fast.
REM ===========================================================================
setlocal EnableDelayedExpansion

set APP_NAME=youtube-downloader
set PYTHON=python

if exist venv\Scripts\python.exe (
    set PY=venv\Scripts\python.exe
) else if exist .venv\Scripts\python.exe (
    set PY=.venv\Scripts\python.exe
)

echo [win] using python: !PY!
echo [win] version:      %VERSION%

where g++.exe >nul 2>nul
if errorlevel 1 (
    where x86_64-w64-mingw32-g++.exe >nul 2>nul
    if errorlevel 1 (
        echo [win] GCC not found - skipping native splash launcher, building exe only.
        goto :skip_splash
    )
    set GXX=x86_64-w64-mingw32-g++
) else (
    set GXX=g++
)

REM ---- 1. Icons -------------------------------------------------------------
%PY% build\make_icons.py
if errorlevel 1 goto :fail

REM ---- 2. Native C++ splash launcher ----------------------------------------
echo [win] building native splash launcher
%GXX% -O3 -std=c++17 -static -municode -mwindows ^
     -o dist\launcher.exe splash\launcher_win.cpp -lgdi32
if errorlevel 1 (
    echo [win] launcher build failed -- continuing without it.
)

:skip_splash

REM ---- 3. PyInstaller bundle -------------------------------------------------
echo [win] ensuring pyinstaller...
%PY% -m pip install --quiet --upgrade pyinstaller

echo [win] making icons...
%PY% build\make_icons.py

echo [win] building exe (this can take a few minutes)...
%PY% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name %APP_NAME% ^
    --onefile ^
    --windowed ^
    --icon build\icons\youtube-downloader.ico ^
    --add-data "youtube-dl.png;." ^
    --add-data "build\icons;icons" ^
    --hidden-import secretstorage ^
    --hidden-import jeepney ^
    --hidden-import cffi ^
    --hidden-import "PIL._tkinter_finder" ^
    main.py
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