@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo Generando biblioteca local para IA desde export_pde...
".venv\Scripts\python.exe" build_ai_corpus.py --out export_pde
set "RET=%ERRORLEVEL%"
if "%RET%"=="0" echo [OK] export_pde\ai_library\study_pack_path_16.zip
pause
exit /b %RET%
