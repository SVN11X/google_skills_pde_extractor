@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === PATH 16: REVISAR SOLO LA LECCION RISE 592746 ===
echo No inicia cuestionarios ni vuelve a transcribir videos.
echo Conserva todo el contenido previamente exportado.
echo.
if not exist ".venv\Scripts\python.exe" (
 echo [ERROR] Entorno .venv no encontrado.
 pause
 exit /b 2
)
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only html_bundle --only-url "https://www.skills.google/paths/16/course_templates/52/html_bundles/592746" --retry-partial --delay 0
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u audit_complete_path.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u build_ai_corpus.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u package_full_export.py --out export_pde
if errorlevel 1 goto :error
echo.
echo [LISTO] Revisa export_pde\resource_coverage_report.json
echo [LISTO] Si no queda verificada, adjunta rise_detached_lesson_mapping.json si existe.
pause
exit /b 0
:error
echo [ERROR] Comparte la salida y los motivos de la auditoria. No se borro nada.
pause
exit /b 1
