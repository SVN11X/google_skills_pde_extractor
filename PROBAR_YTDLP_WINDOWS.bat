@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Comprobar yt-dlp (un solo video) - Google Skills PDE
echo === PRUEBA AISLADA DE YT-DLP ===
echo No se ejecutara el scraper completo. El avance en export_pde no se borra.
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: falta .venv\Scripts\python.exe. Instala las dependencias del proyecto primero.
  pause
  exit /b 1
)
echo.
echo Actualizando yt-dlp y los componentes EJS DENTRO del entorno local...
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]"
if errorlevel 1 (
  echo ERROR instalando yt-dlp. Revisa la conexion o pip.
  pause
  exit /b 1
)
if not exist ".tools\deno\deno.exe" (
  echo Deno no esta en la ruta local. Comprobando instalacion oficial...
  ".venv\Scripts\python.exe" bootstrap_deno.py
)
echo.
echo Revisando los formatos y descargando UN video de prueba...
".venv\Scripts\python.exe" -u youtube_probe.py --video-id stj830n-1uE
set "ESTADO=%ERRORLEVEL%"
echo.
echo Resultado de la prueba: %ESTADO%
echo Detalles: export_pde\yt_dlp_prueba\diagnostico.json
echo Si falla, NO ejecutes otra vez todos los videos. Comparte el diagnostico.
pause
exit /b %ESTADO%
