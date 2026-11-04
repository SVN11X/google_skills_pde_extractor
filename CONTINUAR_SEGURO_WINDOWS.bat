@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Google Skills - Continuar con proteccion contra bloqueos
if not exist ".venv\Scripts\python.exe" (
 echo ERROR: No se encuentra .venv en esta carpeta.
 echo Copia estos archivos ENCIMA de tu carpeta ORIGINAL google_skills_pde_extractor.
 echo Conserva export_pde, .venv, .tools y .google_skills_browser.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" watchdog_runner.py
set "RESULTADO=%ERRORLEVEL%"
echo.
echo Estado final: %RESULTADO%
echo Revisar export_pde\coverage_report.json y export_pde\execution.log
pause
exit /b %RESULTADO%
