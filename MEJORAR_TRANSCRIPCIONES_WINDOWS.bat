@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === WHISPER HQ PARALELO - MODELO LARGE-V3 UNICO ===
echo Usa SOLO los archivos source.* locales; no descarga videos de YouTube.
echo Conserva transcript.* originales y transcript_hq.* ya completados.
echo Para proteger la RAM, el modo AUTO elige 1 o 2 workers.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No existe .venv\Scripts\python.exe
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -I -c "import av,numpy,ctranslate2;from faster_whisper import WhisperModel;print('Whisper OK')"
if errorlevel 1 (
  echo [ERROR] Falta una dependencia. Ejecuta RECUPERAR_TRANSCRIPCIONES_WINDOWS.bat.
  pause
  exit /b 2
)
echo.
echo Probando DOS videos pendientes en paralelo para comparar velocidad y memoria.
echo El modelo large-v3 solo se cargara una vez para este lote.
".venv\Scripts\python.exe" -u upgrade_transcripts.py --out export_pde --model large-v3 --beam-size 5 --workers auto --cpu-threads auto --limit 2
set "RET=%ERRORLEVEL%"
echo.
echo Para terminar TODOS los videos pendientes con el motor paralelo:
echo   .\.venv\Scripts\python.exe -u upgrade_transcripts.py --out export_pde --model large-v3 --workers auto --cpu-threads auto --limit 0
echo Puedes fijar --workers 2 --cpu-threads 4 si tu PC tiene al menos 8 nucleos fisicos.
echo Revisar export_pde\hq_upgrade_report.json
pause
exit /b %RET%
