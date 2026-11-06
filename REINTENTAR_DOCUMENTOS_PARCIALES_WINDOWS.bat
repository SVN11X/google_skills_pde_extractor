@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === RECUPERACION SELECTIVA DE DOCUMENTOS PARCIALES ===
echo Reutiliza los documentos recuperados y prueba solamente los pendientes.
echo Comprueba enlaces alternativos y botones Download document visibles.
echo No abre ni inicia cuestionarios. No borra datos.
echo.
if not exist ".venv\Scripts\python.exe" (
 echo [ERROR] Falta .venv\Scripts\python.exe
 pause
 exit /b 2
)
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only document --retry-partial --delay 2
if errorlevel 1 (
 echo [ERROR] Recuperacion parcial detenida; se conserva el avance.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" -u audit_complete_path.py --out export_pde
".venv\Scripts\python.exe" -u build_ai_corpus.py --out export_pde
if errorlevel 1 echo [AVISO] Error al actualizar la biblioteca; los PDFs permanecen guardados.
".venv\Scripts\python.exe" -u package_full_export.py --out export_pde
if errorlevel 1 echo [AVISO] Error al actualizar archivo completo; comprueba bloqueo de ZIP.
echo Revisa export_pde\resource_coverage_report.json y export_pde\ai_library\latest_pack.json
pause
