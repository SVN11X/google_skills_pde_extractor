@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === WHISPER LARGE-V3: MEJORA SIN BORRAR TRANSCRIPCIONES ===
echo Solo archivos source.* locales. No se descarga de YouTube.
echo Se preservan transcript.txt y transcript.json originales.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Primero prepara el entorno .venv con Faster-Whisper.
  pause
  exit /b 2
)
echo [1/2] Verificando dependencias...
".venv\Scripts\python.exe" -I -c "import av,numpy,ctranslate2;from faster_whisper import WhisperModel;print('Motor Whisper OK')"
if errorlevel 1 (
  echo [ERROR] Faltan dependencias: ejecuta RECUPERAR_TRANSCRIPCIONES_WINDOWS.bat.
  pause
  exit /b 2
)
echo.
echo [2/2] Prueba de alta calidad: un video, beam_size=5, CPU INT8.
echo La primera ejecución puede descargar el modelo grande una sola vez.
".venv\Scripts\python.exe" -u upgrade_transcripts.py --out export_pde --model large-v3 --beam-size 5 --limit 1
set "RET=%ERRORLEVEL%"
echo.
echo Para actualizar TODOS los videos locales disponibles, ejecuta:
echo   .\.venv\Scripts\python.exe upgrade_transcripts.py --out export_pde --model large-v3 --limit 0
echo Revisa export_pde\hq_upgrade_report.json
pause
exit /b %RET%
