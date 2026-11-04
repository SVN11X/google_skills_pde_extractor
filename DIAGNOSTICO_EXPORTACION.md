# Diagnóstico de la ejecución del 4 de noviembre de 2026

Se revisaron los archivos reales `Pasted text(20261104-031003).txt` y `export_pde.zip` entregados por el usuario.

## Extracción previa

| Métrica | Resultado |
|---|---:|
| Actividades semilla | 13 |
| URLs visitadas por el programa anterior | 500 |
| Estado OK anterior | 384 |
| Errores/parciales anteriores | 116 |
| Imágenes descargadas | 169 |
| IDs de YouTube identificados | 177 |
| Transcripciones válidas | 27 |
| Videos sin transcripción | 150 |
| Videos con fotogramas | 0 |
| Fotogramas | 0 |
| URLs pendientes según el informe anterior | 120 |

## Depuración de las URLs de páginas

* **374** URLs de contenido real con estado `ok`.
* **1** URL de contenido real `partial`.
* **125** URLs visitadas de acciones o fuera del alcance (por ejemplo `complete_button`, `enroll`, `resume_on_desktop_email`), que no deben integrarse al conteo de material educativo.
* **24** URLs pertinentes que siguen sin visitarse (laboratorios y documentación), según el estado de la ejecución anterior.

Por tanto, **no deben interpretarse los 120 pendientes originales como 120 lecciones faltantes**.

## Causa del problema con los videos

El log muestra que el entorno ya tenía instalado `yt-dlp` 2025.9.5 y que YouTube respondió reiteradamente: `The page needs to be reloaded`. La herramienta obtuvo 27 transcripciones por la API de subtítulos, pero no descargó archivos de video; por eso no produjo capturas de fotogramas. A partir de la versión 2025.11.12 yt-dlp recomienda un runtime JavaScript externo, especialmente Deno, acompañado del paquete `yt-dlp-ejs`.

## Corrección aplicada

1. Actualización de `yt-dlp[default]`, con EJS, en la ejecución de Windows.
2. Instalación local de Deno verificada mediante su SHA256 oficial, cuando sea necesario.
3. Exclusión de endpoints de acciones que no corresponden a materiales y podrían alterar el progreso.
4. Se conservan transcripciones y fotogramas existentes al reanudar, evitando volver a procesarlos.
5. Se evita descargar otra vez las imágenes existentes.
6. Se amplía el límite de navegación por ejecución a 2.000 páginas de contenido (sin las rutas auxiliares).
7. Reutilización del `crawl_state.json` y los metadatos existentes.
8. Soporte de subtítulos `.vtt` y `.srt` y búsqueda de otras pistas si no hay español/inglés.

La corrección fue comprobada con **8 pruebas locales** y análisis estático del programa. **No se ha ejecutado la extracción de red completa con la sesión de Google Skills del usuario**; por eso la cantidad final de videos e imágenes recuperados depende del acceso real.

Referencias oficiales:
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://docs.deno.com/runtime/getting_started/installation/
