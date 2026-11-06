@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === PATH 16: CAPTURA PROFUNDA DE LAS 59 LECCIONES RISE ===
echo Recorre bloques, pestañas, acordeones, tarjetas y graficos visibles.
echo No inicia cuestionarios, no envia respuestas y no transcribe videos.
echo Guarda avance despues de cada leccion. Reanuda si se interrumpe.
echo.
if not exist ".venv\Scripts\python.exe" (
 echo [ERROR] No se encontro .venv\Scripts\python.exe
 pause
 exit /b 2
)
".venv\Scripts\python.exe" -u deep_capture_path16.py --out export_pde --profile-dir .google_skills_browser --kind rise --max-controls 60 --max-screenshots 12 --max-images 24 --delay 2
if errorlevel 1 goto :error
echo.
echo === PREVISUALIZACION SIN INICIAR LOS 41 QUIZZES ===
".venv\Scripts\python.exe" -u deep_capture_path16.py --out export_pde --profile-dir .google_skills_browser --kind quiz --delay 2
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --audit-only
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u build_ai_corpus.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u package_full_export.py --out export_pde
if errorlevel 1 goto :error
echo.
echo [LISTO] export_pde\rise_deep_coverage_report.json
echo [LISTO] export_pde\rise_deep_manifest.json
echo [LISTO] export_pde\ai_library\latest_pack.json
pause
exit /b 0
:error
echo [ERROR] Se conserva el avance anterior. Comparte el error y el informe.
pause
exit /b 1
