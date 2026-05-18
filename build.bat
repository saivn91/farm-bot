@echo off
title HayDay Farm Bot - Build
echo ============================================
echo  HayDay Farm Bot - Building EXE...
echo ============================================
echo.

REM --- Install dependencies if needed ---
echo [1/3] Checking dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo ERROR: pip install failed.
    pause & exit /b 1
)

REM --- Clean previous build ---
echo [2/3] Cleaning old build files...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec

REM --- Build with PyInstaller ---
echo [3/3] Building EXE with PyInstaller...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "HayDayFarmBot" ^
    --icon "assets\icon.ico" ^
    --add-data "templates;templates" ^
    --add-data "assets;assets" ^
    --hidden-import customtkinter ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import cv2 ^
    --hidden-import pytesseract ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed! Check output above.
    pause & exit /b 1
)

echo.
echo ============================================
echo  BUILD SUCCESSFUL!
echo  Output: dist\HayDayFarmBot.exe
echo ============================================
echo.

REM --- Copy templates to dist ---
if exist "templates" xcopy /s /e /y "templates" "dist\templates\" >nul
if exist "assets"    xcopy /s /e /y "assets"    "dist\assets\"    >nul

echo Files copied to dist\ folder.
echo.
pause
