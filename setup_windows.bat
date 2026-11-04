@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 (echo Fallo creando venv. Instala Python 3.11+ & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
if errorlevel 1 (echo Fallo instalacion Playwright & pause & exit /b 1)
echo Instalacion completa.
pause
