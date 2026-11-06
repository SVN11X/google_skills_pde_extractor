# Google Skills — recuperación de recursos omitidos y auditoría por path

## Objetivo y alcance

Esta actualización se aplica **después** de la extracción principal. Preserva
`export_pde`, los archivos multimedia, las 131 transcripciones originales/HQ,
los manifiestos previos y el perfil local de Playwright. No ejecuta Whisper
ni vuelve a rastrear las 354 páginas conocidas. Abre únicamente las URLs de
recursos cuyo `metadata.json` ya fue guardado para recuperar contenidos.

La auditoría del Path 16 detectó **43 documentos, 35 HTML bundles y 41
quizzes** dentro del corpus; el primer inventario usa exactamente esos
119 recursos cuando se le suministra la exportación correspondiente. El
catálogo original representa las 13 actividades (12 cursos y un laboratorio
independiente `/focuses/2794`).

## Procedimiento sugerido

```powershell
cd C:\my_drive\Portafolio\google_skills_pde_extractor
.\AUDITAR_RECURSOS_OFFLINE_WINDOWS.bat
.\RECUPERAR_CONTENIDO_FALTANTE_WINDOWS.bat
```

**Importante:** la navegación web necesita tu sesión de Google Skills en
`.google_skills_browser`, ya existente. No se pide copiar cookies a archivos,
ni se intentan eludir restricciones HTTP 401/403/429 o CAPTCHA.

El BAT verifica `pypdf` en `.venv` y lo instala localmente si falta; no modifica `requirements.txt`. Obtiene los documentos permitidos, lee las pantallas visibles de las
lecciones HTML en pestañas independientes (incluidos frames accesibles),
guarda capturas y texto, genera la nueva auditoría y actualiza la biblioteca
textual para IA. Sus resultados son incrementales y reiniciables.

**Los quizzes no se inician por defecto:** a veces el botón «Start quiz» consume
un intento o modifica el progreso del usuario. Si quieres acceder a las
preguntas visibles, existe un segundo BAT que pide una única confirmación
explícita antes de intentar entrar:

```powershell
.\REVISAR_QUIZZES_CON_INICIO_OPCIONAL_WINDOWS.bat
```

Nunca responde, marca opciones ni envía un cuestionario. Si no puedes navegar
a la pregunta siguiente sin responder, el resultado será `partial`; **no** se
inventan preguntas ni soluciones.

## Archivos producidos

- `export_pde/resources_manifest.json`: estado y ruta local por URL de recurso.
- `export_pde/resource_coverage_report.json`: inventario por recurso, estados
  `recovered`, `partial`, `blocked`, `failed`, `not_attempted`, con razones.
- `export_pde/extraction_integrity_report.json`: páginas/core frente a referencias
  externas, 13 actividades, videos HQ, fotogramas, imágenes y documentos locales.
- `export_pde/assets/documents/`: binarios descargados legalmente, checksum SHA-256.
- `export_pde/pages/*/embedded_content.md`: texto visible de cursos HTML.
- `export_pde/pages/*/embedded_screenshots/`: capturas de pantallas visibles de
  diapositivas; pueden existir pantallas no alcanzadas/ramas interactivas.
- `export_pde/pages/*/quiz_visible_questions.md`: preguntas visibles (si se
  habilitó explícitamente y la plataforma las mostró).
- `export_pde/ai_library/`: JSONL y Markdown más el índice de recursos; los
  recursos parciales conservan esa etiqueta, nunca figuran como completos.
- `export_pde/complete_archive/path_16_recursos_completos.zip`: copia local
  con Markdown/JSON, documentos, imágenes, capturas, fotogramas y subtítulos,
  sin archivos fuente de audio/video pesados por defecto, con manifiesto de
  inclusión/omisiones y URLs firmadas saneadas.

Para incluir los audios/videos fuente en el ZIP, si su espacio disponible lo
permite:

```powershell
.\.venv\Scripts\python.exe package_full_export.py --out export_pde --include-source-media
```

Para otras rutas ya descargadas:

```powershell
.\.venv\Scripts\python.exe recover_path_resources.py --out export_paths\path_123 --profile-dir .google_skills_browser
.\.venv\Scripts\python.exe audit_complete_path.py --out export_paths\path_123
.\.venv\Scripts\python.exe build_ai_corpus.py --out export_paths\path_123
.\.venv\Scripts\python.exe package_full_export.py --out export_paths\path_123
```

## Criterios de completitud

- Los documentos se consideran `recovered` solamente cuando el archivo binario
  válido se ha descargado y verificado localmente (si se trata de PDF, se
  comprueba la firma `%PDF-`). La extracción de texto PDF usa `pypdf` como
  dependencia; páginas escaneadas podrían carecer de texto sin OCR.
- Las lecciones HTML guardan pantallas visibles y capturas, pero se **marcan
  `partial`** hasta poder demostrar que se han recorrido todos sus estados.
- Los quizzes se mantienen `partial` incluso si algunas preguntas son visibles,
  salvo una futura verificación de preguntas completas sin envío ni respuestas.
- `completion_status=complete` en un informe anterior solo indicaba éxito de
  rastreo/transcripción, **no** exhaustividad pedagógica del Path 16.
- Si existen contenidos bloqueados por la plataforma, el informe mostrará la
  restricción y no declarará artificialmente cobertura total.

## Seguridad y reanudación

No borrar `export_pde`, `.venv`, `.google_skills_browser`. No subir el perfil ni
archivos `export_pde/` a GitHub. Los enlaces firmados de Google Storage se usan
solo durante la descarga y se eliminan de los índices y ZIP compartibles.
El programa deja los estados y archivos originales intactos al fallar.
