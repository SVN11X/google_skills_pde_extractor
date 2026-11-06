@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo === RECUPERAR PREGUNTAS VISIBLES DE QUIZZES (OPCIONAL) ===
echo.
echo ATENCION: Entrar a un quiz puede consumir intentos o cambiar su estado.
echo El programa NUNCA responde ni envia respuestas ni calificaciones.
echo Captura unicamente las preguntas/alternativas que la plataforma muestre.
echo Si la plataforma exige responder para continuar, se registra como parcial.
echo.
set /p "CONFIRM=Escribe SI para autorizar el inicio de quizzes: "
if /I not "%CONFIRM%"=="SI" (
 echo Cancelado. No se inicio ningun quiz.
 pause
 exit /b 0
)
".venv\Scripts\python.exe" -u recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only quiz --enter-quizzes --delay 3
set "RET=%ERRORLEVEL%"
".venv\Scripts\python.exe" -u audit_complete_path.py --out export_pde
if "%RET%"=="0" ".venv\Scripts\python.exe" build_ai_corpus.py --out export_pde
pause
exit /b %RET%
