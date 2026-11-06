@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ==== AUDITORIA Y RECUPERACION DE RECURSOS DE GOOGLE SKILLS ====
echo No borra export_pde ni el perfil de Google Skills.
echo Recupera documentos, contenido de iframe y cuestionarios YA visibles.
echo IMPORTANTE: No inicia cuestionarios que puedan consumir intentos.
echo.
if not exist ".venv\Scripts\python.exe" (
 echo [ERROR] Falta entorno virtual .venv
 pause
 exit /b 2
)
rem PDF text extraction uses PyPDF; check the isolated venv interpreter.
".venv\Scripts\python.exe" -I -c "from pypdf import PdfReader" >nul 2>&1
if errorlevel 1 (
 echo [DEPENDENCIA] Instalando pypdf en el entorno virtual para extraer texto de PDFs...
 ".venv\Scripts\python.exe" -m pip install --upgrade --ignore-installed "pypdf>=5,<7"
 if errorlevel 1 (
  echo [ERROR] No se pudo instalar pypdf. No se modificaron las exportaciones.
  pause
  exit /b 3
 )
 ".venv\Scripts\python.exe" -I -c "from pypdf import PdfReader" >nul 2>&1
 if errorlevel 1 (
  echo [ERROR] pypdf no se puede importar desde .venv. Revisa la instalacion.
  pause
  exit /b 3
 )
)
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --delay 2
set "RET=%ERRORLEVEL%"
echo.
echo INFORME: export_pde\resource_coverage_report.json
echo.
if not "%RET%"=="0" (
 echo [ERROR] La recuperacion finalizo con errores. No se borro el avance.
 pause
 exit /b %RET%
)
".venv\Scripts\python.exe" -u audit_complete_path.py --out export_pde
".venv\Scripts\python.exe" build_ai_corpus.py --out export_pde
".venv\Scripts\python.exe" package_full_export.py --out export_pde
pause
