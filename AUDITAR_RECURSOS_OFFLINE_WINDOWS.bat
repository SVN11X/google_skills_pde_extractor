@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
".venv\Scripts\python.exe" recover_path_resources.py --out export_pde --audit-only
pause
