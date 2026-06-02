@echo off
title Group Manager Bot - Installer
color 0A

echo ============================================
echo    Telegram Group Manager Bot - Setup
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not installed!
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found
echo.
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo ============================================
echo    Done! Edit config.py then run START.bat
echo ============================================
pause
