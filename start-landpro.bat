@echo off
rem ---------------------------------------------------------------
rem ABI LAND Records Management System - one-click Windows launcher
rem Double-click this file to set up and start the web application.
rem ---------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"
title ABI LAND Records Management System
echo.
echo   ABI LAND Records Management System
echo   ---------------------------------
echo.

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    echo Python 3.12 or newer is required.
    echo Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then start again.
    echo.
    pause
    exit /b 1
)

"%PYEXE%" "%~dp0scripts\run_local.py" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo ABI LAND stopped. Start it again any time with start-landpro.bat
) else (
    echo ABI LAND exited with code %RC%. Review the messages above or see README.md
)
echo.
pause
exit /b %RC%
