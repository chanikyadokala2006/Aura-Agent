@echo off
color 0B
title Aura - Cognitive OS Initializer
echo ===================================================
echo   Starting Aura Cognitive Architecture...
echo ===================================================
echo.
echo [1/2] Booting React UI Engine (Background)...
start /min "Aura UI Server" cmd /c "cd src\renderer && npm run dev"

echo [2/2] Booting Python Agent Core...
timeout /t 3 /nobreak > nul
call venv\Scripts\activate.bat
cd src\main
python main.py

echo.
echo Closing launcher...
exit
