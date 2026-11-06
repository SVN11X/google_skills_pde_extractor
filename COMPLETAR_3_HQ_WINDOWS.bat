@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === COMPLETAR WHISPER LARGE-V3: SOLO LOS HQ PENDIENTES ===
echo No recorre Google Skills, no abre Chrome ni borra export_pde.
echo Reutiliza medios de otros paths y solo descarga el audio imprescindible.
echo Ante HTTP 429 detiene las descargas restantes y conserva todo.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Falta .venv\Scripts\python.exe
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -I -c "import av,numpy,ctranslate2;from faster_whisper import WhisperModel;print('Faster-Whisper OK')"
if errorlevel 1 (
  echo [ERROR] Faltan dependencias Whisper en .venv.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -u complete_hq.py --out export_pde --model large-v3 --fetch-missing --max-downloads 3 --workers auto --cpu-threads auto
set "RET=%ERRORLEVEL%"
echo.
echo INFORME: export_pde\hq_completion_report.json
echo BIBLIOTECA: export_pde\ai_library\study_pack_path_16.zip
echo Si quedan HQ pendientes revisa el informe; codigo 3 significa cobertura parcial.
pause
exit /b %RET%
