@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === PATH 16: AUDITORIA Y REPARACION SELECTIVA DE CAPTURAS RISE ===
echo NO inicia quizzes, NO elimina evidencia, NO re-transcribe videos.
echo Revisa solo las lecciones con mas estados que capturas disponibles.
echo Los originales se conservan en rise_deep_prev si la nueva captura mejora.
echo.
if not exist ".venv\Scripts\python.exe" (
 echo [ERROR] Falta .venv\Scripts\python.exe
 pause
 exit /b 2
)
".venv\Scripts\python.exe" -u auditar_rise_deep.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u deep_capture_path16.py --out export_pde --profile-dir .google_skills_browser --kind rise --repair-screenshots --max-controls 60 --max-screenshots 64 --max-images 24 --delay 2
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u auditar_rise_deep.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u build_ai_corpus.py --out export_pde
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -u package_full_export.py --out export_pde
if errorlevel 1 goto :error
echo.
echo [LISTO] export_pde\rise_deep_gap_audit.json
echo [LISTO] export_pde\rise_deep_gap_priority.csv
echo [LISTO] export_pde\ai_library\latest_pack.json
pause
exit /b 0
:error
echo [ERROR] Se conserva la evidencia anterior. Envia el mensaje para revisar.
pause
exit /b 1
