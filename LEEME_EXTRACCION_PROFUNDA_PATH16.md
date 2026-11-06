# Google Skills Path 16 - captura profunda Rise (parche sobre d45999c)

## Qué modifica

- **Nuevo** `deep_capture_path16.py`: abre las lecciones Rise ya enumeradas en `export_pde/pages`, conserva el fragmento `#/lessons/ID`, exige concordancia con `data-lesson-id` y captura texto visible por `data-block-id`.
- Recorre controles de lectura no evaluativos (pestañas, acordeones, fichas, marcadores de gráficos). Los botones de quiz, comenzar, enviar, comprobar, continuar y navegación entre lecciones quedan excluidos.
- Guarda los estados de texto distintos, capturas PNG de bloques cambiados y copias limitadas de imágenes visualizadas cuando el recurso es estático y está permitido.
- **Nuevo** `export_pde/rise_deep_manifest.json`, `rise_deep_coverage_report.json` y `pages/.../rise_deep/lesson_blocks.json`, `lesson_content.md`, `screenshots/`, `images/`.
- Captura las preguntas **ya visibles** en páginas de quiz sin pulsar «Start quiz». No intenta revelar contenido que requiera comenzar o responder una evaluación.
- `build_ai_corpus.py` incorpora un nuevo tipo `rise_deep_observation`, identificado explícitamente como **cobertura parcial**, conservando los chunks anteriores y su procedencia.

## Pasos

1. Confirmar `git status` limpio y rama `main` actualizada (`d45999c` o posterior).
2. Aplicar el parche **una vez** con `git am "$env:USERPROFILE\Downloads\GoogleSkills_PATH16_EXTRACCION_PROFUNDA_20261106.patch"`.
3. Para una prueba pequeña: `PROBAR_UNA_LECCION_RISE_WINDOWS.bat`.
4. Para todos los 59 Rise y verificar los 41 cuestionarios sin iniciarlos: `EXTRACCION_PROFUNDA_RISE_PATH16_WINDOWS.bat`.
5. Revisar `export_pde\rise_deep_coverage_report.json` y `export_pde\rise_deep_manifest.json`.
6. Si lo deseas, `git push origin main` (las exportaciones deben seguir fuera de Git).

## Garantías y límites

- No cambia `requirements.txt`, `export_pde` anterior, `.google_skills_browser` ni los 131 videos.
- Reanuda por lección y persiste manifiesto por cada resultado. Los recursos ya capturados se saltan; agrega `--force` solo para reemplazar una captura del mismo recurso deliberadamente.
- No usa API privadas ni evade controles de acceso. Si una página muestra 401/403/429 se registra sin intentar sortearla.
- No afirma cobertura completa de bloques interactivos ocultos tras condiciones, ni cuestionarios no iniciados. Las 59 lecciones permanecen `partial` hasta que una auditoría pueda demostrar exhaustividad.
- Algunos controles visuales no se parecen a los soportados o pueden requerir acciones manuales; quedan reflejados en el inventario. Las imágenes externas, autenticadas o mayores al límite se referencian o quedan pendientes.
