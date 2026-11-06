# Path 16 — verificación aislada de la primera lección Rise

**Base:** `main` de `SVN11X/google_skills_pde_extractor`, commit `8200d48`.

La lección `https://www.skills.google/paths/16/course_templates/52/html_bundles/592746`
contiene un iframe `ql-iframe` con una ruta precisa de Articulate Rise:

`https://storage.googleapis.com/cloud-training/cls-html5-courses/T-STREAM-I/3.0/T-STREAM-I/content/index.html#/lessons/Lrz7-fyK5nYDZubm2TA2ba-YjsNGcJJN`

La captura original de Google Skills es solo el contenedor: el HTML interno del
iframe se carga aparte. La URL **no basta** para verificar el contenido. Esta
corrección permite esperar al iframe y, si no se carga dentro de Google Skills,
abrir **esa misma ruta** en otra pestaña para verificar `data-lesson-id` contra
el identificador del hash y registrar los bloques visibles.

## Instalar

```powershell
cd C:\my_drive\Portafolio\google_skills_pde_extractor
git status
git pull --ff-only origin main
git am "$env:USERPROFILE\Downloads\GoogleSkills_PATH16_RISE_592746_FALLBACK_20261106.patch"
```

## Ejecutar solo la lección 592746

```powershell
.\REVISAR_592746_RISE_WINDOWS.bat
```

Equivalente sin BAT:

```powershell
.\.venv\Scripts\python.exe -u .\recover_path_resources.py --out export_pde --profile-dir .google_skills_browser --only html_bundle --only-url "https://www.skills.google/paths/16/course_templates/52/html_bundles/592746" --retry-partial --delay 0
```

El BAT también actualiza la auditoría y los archivos ZIP. No vuelve a descargar
las 131 transcripciones ni inicia cuestionarios. No borres `export_pde` ni el
perfil `.google_skills_browser`.

## Revisar resultado

```powershell
$r = Get-Content '.\export_pde\resource_coverage_report.json' -Raw | ConvertFrom-Json
$r.resources | Where-Object { $_.url -match '/592746$' } |
  Select-Object url, lesson_mapping_verified, lesson_mapping_source, lesson_id, visible_block_count, reason |
  Format-List
```

- `lesson_mapping_source=inline_iframe`: el iframe de Google Skills se verificó.
- `lesson_mapping_source=detached_verified`: la misma ruta se verificó en una pestaña aislada.
- `lesson_mapping_source=unverified`: no se pudo verificar todavía, sin afirmar falsamente éxito.
- El estado `partial` **continuará siendo correcto** hasta comprobar todas las pestañas, interacciones, imágenes y otros recursos internos.

La evidencia de navegación queda en `rise_lesson_mapping.json` o
`rise_detached_lesson_mapping.json` dentro de la carpeta de esa página en
`export_pde/pages`.

Si sigue sin verificarse, es preferible compartir el HTML de la pestaña Rise
abierta directamente (la URL `storage.googleapis.com/.../index.html#/lessons/...`),
no otra copia del contenedor de Google Skills. Evita compartir cookies,
credenciales o archivos HAR de sesión.
