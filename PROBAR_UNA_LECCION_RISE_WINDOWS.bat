@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo === PRUEBA DE UNA LECCION RISE - 631438 ===
echo No borra archivos, no modifica la extraccion original.
".venv\Scripts\python.exe" -u deep_capture_path16.py --out export_pde --profile-dir .google_skills_browser --only-url https://www.skills.google/paths/16/course_templates/54/documents/631438 --limit 1 --delay 0
if errorlevel 1 (
 echo [ERROR] Comparte el mensaje mostrado.
 pause
 exit /b 1
)
echo [LISTO] Prueba terminada. Revisa export_pde\rise_deep_coverage_report.json
pause
