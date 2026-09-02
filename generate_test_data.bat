@echo off
chcp 65001 >nul
setlocal
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual env not found. Please run start.bat first to install dependencies.
    pause
    exit /b 1
)
set PYTHONUTF8=1
echo Generating and importing test knowledge base into Milvus...
echo (first run loads the local embedding model, be patient)
".venv\Scripts\python.exe" -m scripts.generate_test_data
pause