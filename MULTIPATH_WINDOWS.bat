@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo === GOOGLE SKILLS: MULTIPLES LEARNING PATHS ===
echo Edita paths.txt (una URL https://www.skills.google/paths/NUMERO por linea).
echo Se comparte SOLO el perfil de Chrome; cada path tiene su exportacion propia.
echo El proceso corre secuencialmente. No borra datos anteriores.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No existe .venv\Scripts\python.exe
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u multi_path.py --paths-file paths.txt --mode crawl
set "RET=%ERRORLEVEL%"
if "%RET%"=="0" echo [OK] Bibliotecas: export_paths\path_ID\ai_library y export_paths\combined_ai_library
pause
exit /b %RET%
