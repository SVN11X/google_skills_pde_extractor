# Path 16 — auditoría de huecos y reparación visual selectiva

## Qué reveló `rise_deep_manifest.json`

- 59 lecciones Rise, 1.217 bloques inspeccionados, 694 controles activados.
- 408 estados observados y 301 capturas de dichos estados; **107 estados sin captura PNG**, repartidos en 13 lecciones.
- Las 13 lecciones alcanzaron el límite anterior de 12 capturas. El nuevo límite predeterminado es **64 por lección**.
- 20 lecciones sin controles activados requieren revisión (podrían ser estáticas; no equivale automáticamente a un fallo).
- 41 cuestionarios verificados en vista inicial, sin preguntas disponibles y sin iniciar intentos.

## Instalación

Aplicar el `.patch` mediante `git am` sobre el repositorio que ya contiene `deep_capture_path16.py` (parche previo de extracción profunda). No aplicar dos veces.

## Uso recomendado

1. Sin conexión: `.venv\Scripts\python.exe auditar_rise_deep.py --out export_pde`.
2. Reparación selectiva: `REPARAR_EVIDENCIA_VISUAL_RISE_PATH16_WINDOWS.bat`.
3. Revisar `export_pde\rise_deep_gap_audit.json` y `rise_deep_gap_priority.csv`.
4. Si los resultados son adecuados, `git push origin main`.

En la reparación, se vuelven a abrir **solo** los registros Rise que tengan `states_captured > screenshots_saved`. Cada nueva extracción se produce en una carpeta temporal y se compara con la anterior. Solo si iguala o mejora bloques/estados/imágenes y aumenta las capturas se mueve a la carpeta vigente. El material anterior se respalda completo bajo `rise_deep_prev` y nunca se borra. Las URLs de las capturas de los JSON se reescriben al directorio definitivo.

No cambia `requirements.txt`, no reinicia las 41 evaluaciones y no repite transcripciones de video. `complete` permanece `false` porque evidencia no equivale a exhaustividad. Si el sitio impide una captura, el informe lo registrará y preservará el resultado anterior.
