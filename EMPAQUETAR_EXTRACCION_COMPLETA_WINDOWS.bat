@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo Empaquetando HTML/textos, PDF, imagenes, capturas, fotogramas y subtitulos.
echo No incluye fuentes de audio/video por defecto para reducir el ZIP.
".venv\Scripts\python.exe" package_full_export.py --out export_pde
pause
