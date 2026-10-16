@echo off
setlocal

REM Build do cliente THLPro para Windows 64-bit

cd /d "%~dp0"

if not exist ".venv" (
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
pip install -r requirements.txt

python build_client.py

echo.
echo Build finalizado. Verifique dist\THLProClient.exe
pause