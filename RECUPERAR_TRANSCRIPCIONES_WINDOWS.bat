@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo === RECUPERAR TRANSCRIPCIONES PENDIENTES - SOLO ARCHIVOS LOCALES ===
echo No abrira Chrome ni repetira descargas de YouTube.
echo Conserva export_pde, perfil, videos y capturas.
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No se encontro .venv\Scripts\python.exe.
  echo Abre este BAT desde la carpeta original del proyecto.
  pause
  exit /b 2
)
if not exist "export_pde\videos_manifest.json" (
  echo [ERROR] No existe export_pde\videos_manifest.json.
  pause
  exit /b 2
)
echo [1/3] Comprobando PyAV y Faster-Whisper bajo el MISMO Python aislado...
".venv\Scripts\python.exe" -I -c "import av; from faster_whisper import WhisperModel; print('PyAV:', av.__version__, '- Faster-Whisper: OK')"
if errorlevel 1 (
  echo.
  echo [2/3] Falta una dependencia. Instalando PyAV dentro de .venv...
  echo Se fuerza la instalacion local porque Python podria ver paquetes globales.
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --ignore-installed --no-deps --only-binary=:all: "av>=11,<17"
  if errorlevel 1 (
    echo [ERROR] No fue posible instalar PyAV. Revisa la salida de pip.
    pause
    exit /b 2
  )
  ".venv\Scripts\python.exe" -I -c "import av; from faster_whisper import WhisperModel; print('PyAV:', av.__version__, '- Faster-Whisper: OK')"
  if errorlevel 1 (
    echo [ERROR] PyAV o Faster-Whisper sigue sin cargarse en modo aislado.
    echo Prueba: .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 2
  )
) else (
  echo [2/3] Dependencias verificadas; no se necesita reinstalacion.
)
echo.
echo [3/3] Recuperando solo transcripciones pendientes desde source.* locales...
".venv\Scripts\python.exe" -u recover_transcripts.py --out export_pde --model small
set "RET=%ERRORLEVEL%"
echo.
if not "%RET%"=="0" (
  echo [ATENCION] Revisa export_pde\whisper_recovery_diagnostic.txt
) else (
  echo [OK] Recuperacion local terminada; puede quedar material sin archivo fuente.
)
echo Revisa export_pde\whisper_recovery_summary.json y coverage_report.json.
pause
exit /b %RET%
