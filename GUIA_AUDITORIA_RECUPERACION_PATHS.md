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


## Reejecucion selectiva y ZIP bloqueado (Windows)

Si la primera pasada obtuvo 19/43 documentos y dejo 24 parciales,
`REINTENTAR_DOCUMENTOS_PARCIALES_WINDOWS.bat` reintenta **solo** documentos
incompletos sin descargar los ya recuperados. Admite enlaces alternativos y
botones *Download document* visibles. No inicia quizzes ni modifica respuestas.

Si Windows bloquea `ai_library/study_pack_path_16.zip`, el exportador ahora
crea una nueva copia validada con sufijo `_new_...zip` y registra la ubicación
exacta en `ai_library/latest_pack.json`; el ZIP anterior no se sobrescribe.
Los documentos y la biblioteca completa no se borran por un fallo de bloqueo.

`resource_coverage_report.json` incorpora `unresolved_reasons` por tipo de
recurso. El estado `partial` de los 35 HTML embebidos **no demuestra** que no
haya contenido guardado: puede existir texto y capturas de la parte visible,
pero no evidencia de todas las diapositivas/ramas. Los 41 quizzes permanecen
parciales porque comenzar intentos es una operación independiente con
confirmación. No se afirma extracción exhaustiva del Path 16.

## Documentos que en realidad son lecciones HTML5 (curso T-DLAKES-I)

Las 24 páginas `/course_templates/54/documents/*` tienen un enlace «Download document»
que apunta a **un mismo** `.../T-DLAKES-I/content/index.html`, no a PDF. El
intento anterior produjo `button_download_unavailable` porque el navegador
abre contenido HTML en vez de emitir una descarga de archivo.

Ejecutar `RECUPERAR_DOCUMENTOS_HTML_Y_LECCIONES_WINDOWS.bat` con la sesión de
Google Skills disponible. El programa reutiliza los 19 PDF recuperados; para los
24 documentos HTML captura el **iframe desde la propia lección** a fin de
conservar, cuando sea visible, la sección elegida por la plataforma. Reintenta
luego los 35 `html_bundle` y combina capturas del iframe de la página original
con estados obtenidos de una pestaña aislada. No inicia quizzes.

`resource_coverage_report.json` incorpora `evidence_coverage` para distinguir
recursos parciales con texto o captura guardada de recursos sin evidencia.
Una lección con captura o texto sigue siendo **partial** si no se verificó la
cobertura de todas sus pantallas. Dado que el curso comparte un único
`index.html`, `lesson_mapping_verified` permanece en `false` hasta una
comprobación adicional. Los marcadores de página, el avance y los videos HQ
originales se conservan. El paquete para IA se actualiza al finalizar.

**Importante:** la captura del contenido visible no sustituye descargar todos
los recursos auxiliares de un curso HTML5, ni certifica haber recorrido todas
las interacciones. Ningún resultado debe presentarse como extracción al 100 %
sin un inventario de pantallas y verificación independiente.


## Diagnóstico Rise: conservar la ruta de cada lección (6 noviembre 2026)

Los documentos HTML5 de **Build Data Lakes and Data Warehouses on Google Cloud**
usan un reproductor Articulate Rise. Cada página Google Skills tiene una URL
`content/index.html#/lessons/<id>` distinta. La función general `norm_url()`
del rastreador elimina fragmentos, por lo que los metadatos antiguos solo
guardaban `content/index.html`. Este cambio **no modifica `norm_url()`**: toma
la ruta de la lección que realmente está visible en el iframe de la página
original y la utiliza únicamente en la recuperación selectiva.

El extractor comprueba que el identificador de la URL coincida con
`[data-lesson-id]` en el DOM renderizado. Guarda:

- `rise_lesson_mapping.json` por página, sin cookies, firmas ni URL de sesión.
- `lesson_route`, `lesson_id`, `lesson_title` y `visible_block_count` en
  `resources_manifest.json` y `resource_coverage_report.json`.
- `evidence_coverage.document.with_verified_lesson_mapping` y
  `evidence_coverage.html_bundle.with_verified_lesson_mapping`.
- Texto mostrado y capturas existentes, sin eliminar los originales.

Solo abre una pestaña adicional para una lección Rise cuando dispone de una
ruta con `#/lessons/<id>` y verifica que esa ruta cargó correctamente; nunca
abre el índice genérico para mezclar otra lección. Tampoco pulsa «Next» en
un reproductor Rise: podría pasar a otra lección. La captura sigue siendo
**parcial** hasta que se demuestre la integridad de todas las interacciones.

Para ejecutar en Windows:

```powershell
.\RECUPERAR_DOCUMENTOS_HTML_Y_LECCIONES_WINDOWS.bat
$r = Get-Content .\export_pde\resource_coverage_report.json -Raw | ConvertFrom-Json
$r.evidence_coverage | ConvertTo-Json -Depth 6
```

Los 41 quizzes continúan sin iniciarse ni contestarse automáticamente.
