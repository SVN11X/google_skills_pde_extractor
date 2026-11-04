@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Google Skills PDE - Extraccion completa en una sola ejecucion

echo =============================================================
echo GOOGLE SKILLS PDE - EXTRAER TODO (una sola ejecucion)
echo Cursos, lecciones, laboratorios, articulos, imagenes,
echo capturas de paginas, subtitulos, transcripciones y frames.
echo =============================================================
echo.

REM Priorizar Python 3.12 en Windows cuando este disponible.
set "PYLAUNCHER="
py -3.12 --version >nul 2>&1
if not errorlevel 1 set "PYLAUNCHER=py -3.12"
if not defined PYLAUNCHER (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYLAUNCHER=py -3"
)
if not defined PYLAUNCHER (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYLAUNCHER=python"
)
if not defined PYLAUNCHER (
    echo ERROR: Python 3.11 o superior no esta instalado o no esta en PATH.
    echo Instala Python desde https://www.python.org/downloads/windows/
    goto :failed
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno Python local...
    %PYLAUNCHER% -m venv ".venv"
    if errorlevel 1 goto :failed
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

echo [1/3] Instalando dependencias actuales: yt-dlp, EJS, Whisper y FFmpeg...
"%VENV_PY%" -m pip install --disable-pip-version-check --upgrade -r requirements.txt
if errorlevel 1 goto :failed
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 goto :failed

echo.
echo [1/3] Comprobando Deno para el procesamiento de videos...
"%VENV_PY%" bootstrap_deno.py
if errorlevel 1 echo AVISO: Algunos videos pueden seguir inaccesibles sin Deno.
echo.
echo [2/3] Se abrira Google Skills. Si necesitas iniciar sesion,
echo hazlo en el navegador y pulsa ENTER en esta ventana.
echo No necesitas ejecutar un programa de login aparte.
echo.
echo [3/3] Se explorara la ruta y se extraera tambien cada video.
echo Los resultados estaran en export_pde.
echo.
"%VENV_PY%" extractor.py --all --retry-failed --frame-method both --frame-seconds 10 --max-pages 2000 --delay 2
if errorlevel 1 goto :failed

echo.
echo =============================================================
echo PROCESO FINALIZADO. Comprueba export_pde\coverage_report.json
echo y export_pde\execution.log para errores o material pendiente.
echo =============================================================
pause
exit /b 0

:failed
echo.
echo No se pudo completar el proceso. Revisa el mensaje de error.
echo Puedes volver a ejecutar ESTE MISMO archivo para reintentar.
pause
exit /b 1
