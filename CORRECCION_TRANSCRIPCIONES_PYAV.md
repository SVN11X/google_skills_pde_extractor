# Hotfix para Whisper CPU INT8: dependencia PyAV y transcripciones pendientes

## Problema identificado en el registro real

`Whisper: Whisper CPU (código 1): ModuleNotFoundError: No module named 'av'`.
Faster-Whisper no puede decodificar el medio sin PyAV en el Python del worker.
El bloqueo HTTP 429 de subtítulos de YouTube es independiente de este error; el
script de recuperación **no solicita contenido a YouTube**.

## Instalación desde Git

1. Aplica el parche Git AM o copia los archivos incluidos en el ZIP sobre el repositorio.
2. Conserva `export_pde`, `.venv`, `.tools` y `.google_skills_browser`.
3. Ejecuta `RECUPERAR_TRANSCRIPCIONES_WINDOWS.bat`.
4. La herramienta prueba importar `av` y `faster_whisper` con el mismo `.venv` y
   el mismo modo aislado `-I` del worker. Si hace falta, instala una rueda PyAV
   local aunque pip detecte otra instalación global.
5. Utiliza videos y audios `source.*` que ya estén guardados. No visita páginas
   ni reintenta YouTube. **Solo se transcribe lo que falta.**

## Resultados

- `export_pde/whisper_recovery_summary.json`: videos recuperados, sin medios y pendientes.
- `export_pde/whisper_recovery_diagnostic.txt`: error completo si falla la primera transcripción.
- `export_pde/coverage_report.json`: `youtube_transcripts_pending` y estado `partial` si corresponde.
- `export_pde/videos/<ID>/transcript.txt`: transcripción recuperada.

Si los 89 videos pendientes tienen medios `source.*`, el programa puede intentar
recuperar sus transcripciones sin descargarlos. Si alguno no dispone de medio o
no contiene voz inteligible, quedará pendiente y se registrará. Si la primera
prueba de Whisper falla, el lote se detiene para evitar 89 errores repetidos.

Las capturas no se generan con este BAT: se conservan las existentes.
La falla FFmpeg de extracción por escenas es independiente; una secuencia
por intervalo puede estar disponible incluso si no se detectan cambios de escena.
