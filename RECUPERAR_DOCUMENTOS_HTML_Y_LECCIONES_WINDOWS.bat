@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === GOOGLE SKILLS PATH 16: DOCUMENTOS HTML Y LECCIONES ===
echo Solo recursos incompletos. Conserva PDFs, videos HQ y avance.
echo 24 documentos de un curso comparten index.html: se lee el iframe de cada leccion.
echo Los quizzes no se inician ni se responden.
echo Ninguna pagina se marcara completa solo por guardar capturas.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No se encontro .venv\Scripts\python.exe
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only document --retry-partial --delay 2
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only html_bundle --retry-partial --delay 2
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u audit_complete_path.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u build_ai_corpus.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u package_full_export.py --out export_pde
if errorlevel 1 goto :error
echo.
echo [LISTO] Revisa export_pde\resource_coverage_report.json
echo [LISTO] Biblioteca actual: export_pde\ai_library\latest_pack.json
pause
exit /b 0
:error
echo [ERROR] Se conserva el avance. Comparte el informe y la ultima linea del error.
pause
exit /b 1
