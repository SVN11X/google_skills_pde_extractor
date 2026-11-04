# CORRECCIÓN Y REANUDACIÓN — 4 de noviembre de 2026

**Tu exportación anterior NO está perdida.** Actualiza únicamente los archivos del extractor
(`extractor.py`, `bootstrap_deno.py`, `requirements.txt` y archivos `.bat`) dentro de **la misma carpeta**
que ya contiene tu directorio `export_pde`. No elimines ni reemplaces `export_pde`,
`.google_skills_browser` ni tus datos de sesión.

Haz doble clic en **`CONTINUAR_TODO_WINDOWS.bat`**. El proceso usa la misma salida de antes,
reutiliza las 27 transcripciones ya presentes, reintenta los videos que no tienen capturas
y visita los enlaces de cursos/documentación que realmente falten.

Al comenzar instala/actualiza `yt-dlp[default]` (incluye `yt-dlp-ejs`), Playwright y demás
requisitos; comprueba y, si falta, descarga Deno de GitHub oficial con validación SHA256.
Sin Deno, yt-dlp puede seguir fallando en YouTube. El script registra los fallos en vez de
afirmar que descargó los videos. No evita restricciones de YouTube, permisos ni DRM.

**Si estás ejecutando desde una nueva carpeta vacía**, no encontrarás tu antiguo avance.
Copia primero `export_pde` desde la carpeta de la ejecución anterior a la carpeta nueva.

**Resultados previos examinados:** 500 páginas visitadas (384 OK, 116 incidencias),
169 imágenes descargadas, 177 enlaces a YouTube, 27 transcripciones y 0 fotogramas.
Muchos de los errores de páginas se debían a rutas de acciones (`/enroll`,
`/complete_button`, `/start`), que esta versión deja de visitar.

El número final depende de lo que permita acceder el sitio. El límite del rastreador es
**2.000 visitas de contenido nuevas por ejecución** (no un límite total de páginas históricas)
y el estado se guarda de forma incremental.

Fuentes oficiales: https://github.com/yt-dlp/yt-dlp/wiki/EJS y
https://docs.deno.com/runtime/getting_started/installation/

---

# Google Skills Professional Data Engineer — extractor local

Herramienta para elaborar un inventario verificable y una copia de estudio de **los recursos a los que tienes acceso** desde la ruta oficial:

https://www.skills.google/paths/16

**Estado del entregable**: el archivo `seed_catalog.json` ya contiene las **13 actividades reales** detectadas en el HTML proporcionado (12 cursos y 1 laboratorio). El contenido de sus páginas interiores, materiales, videos y transcripciones **no está incluido en ese HTML**: se obtiene al ejecutar el extractor en tu computadora con acceso a Internet y con la sesión correspondiente, si el curso lo requiere.

## Qué captura

- Estructura de ruta → cursos → módulos → laboratorios y otras actividades que aparezcan enlazadas en sus páginas.
- Títulos, descripciones, URL original, ID y estado de bloqueo cuando la página lo declara.
- Texto visible en el contenido principal como Markdown (`pages/**/content.md`).
- Enlaces externos de artículos, guías, documentación y otras referencias (CSV).
- URL de imágenes y, con una opción adicional, archivos de imagen descargables desde hosts conocidos.
- URL/ID de videos de YouTube incrustados en las páginas recorridas.
- Transcripciones de YouTube: primero `youtube-transcript-api`, luego subtítulos con `yt-dlp`; si configuras `--whisper`, se puede transcribir localmente el audio de videos accesibles sin subtítulos.
- Fotogramas de YouTube automáticamente en el modo `--all`: cada 10 segundos y en cambios de escena; `imageio-ffmpeg` proporciona FFmpeg local.
- Capturas de páginas con `--page-screenshots`.
- Registros de estado de cada URL, errores, recursos pendientes y resultados de transcripción.

## Un clic: extracción integral en Windows

**Ejecuta una sola vez `EXTRAER_TODO_WINDOWS.bat`**, haciendo doble clic. No necesitas usar `setup_windows.bat`, `login_windows.bat` ni ejecutar otro comando después para transcripciones o imágenes.

Antes de comenzar, comprueba que tienes **Python 3.11+** (se prefiere Python 3.12). El archivo BAT hace todo esto dentro de la misma ejecución:

1. Crea `.venv` y instala automáticamente Playwright, `yt-dlp`, `youtube-transcript-api`, `faster-whisper` e `imageio-ffmpeg` (incluye binario FFmpeg local, sin instalarlo globalmente).
2. Instala Chromium para Playwright y abre Google Skills en navegador visible. **Si la cuenta no tiene una sesión activa, debes iniciar sesión manualmente y pulsar ENTER en la misma ventana del proceso**. No hace falta otro archivo ni volver a ejecutar.
3. Recorre la ruta, sus cursos, módulos y laboratorios enlazados, además de los artículos públicos admitidos. Captura texto, metadatos, links, imágenes y capturas de las páginas.
4. Por cada YouTube detectado, busca primero subtítulos/transcripción publicados; de no haberlos, intenta transcribir el audio accesible con Whisper. Para los videos descargables, obtiene **fotogramas cada 10 segundos y en cambios de escena** dentro de la misma ejecución.
5. Guarda todo en `export_pde` e informa cuáles páginas, videos, transcripciones o fotogramas no pudo obtener en `coverage_report.json` y `execution.log`.

**Importante**: no es posible garantizar 100 % de los materiales internos. El sitio puede exigir inscripción/suscripción, impedir el acceso automatizado o no ofrecer archivos descargables. El programa no elude esos controles ni inicia laboratorios. Whisper requiere descargar el modelo en el primer uso y puede necesitar bastante CPU, memoria y espacio en disco. La ejecución completa puede ser prolongada si existen muchos videos.

Si una ejecución se interrumpe, vuelve a hacer doble clic en el mismo BAT: la navegación conserva el estado y los recursos procesados se reutilizan cuando es posible.

### Uso manual opcional

```powershell
.\.venv\Scripts\python.exe extractor.py --all --retry-failed --max-pages 500 --delay 2
```

La opción `--all` activa conjuntamente `--download-images`, `--page-screenshots`, `--frames`, `--whisper`, `--follow-public-articles` y `--login-if-needed`; `--frame-method both` combina muestras temporales y cambios de escena.

### Sólo extraer el índice del HTML que guardaste

```powershell
python extractor.py --offline-seed-only
```

Este modo no hace solicitudes web; produce `initial_catalog.json` y `initial_catalog.csv` con las 13 entradas del `seed_catalog.json` incluido.

Puedes regenerar la semilla desde tu propio archivo HTML (si tiene un menú estructurado):

```powershell
python extractor.py --offline-seed-only --seed-html "C:\Users\TU_USUARIO\Downloads\Professional Data Engineer Certification _ Google Skills.html"
```

### Opciones avanzadas

```powershell
# Artículos públicos enlazados en cloud.google.com, sin recorrer todas sus subsecciones
python extractor.py --follow-public-articles --download-images

# Extraer fotogramas de los videos accesibles cada 5 segundos
python extractor.py --frames --frame-seconds 5 --frame-method interval

# Combinar ambos métodos de captura (valor predeterminado de --all)
python extractor.py --frames --frame-method both

# Transcribir con IA local cuando no hay subtítulos publicados
pip install faster-whisper
python extractor.py --whisper --whisper-model small

# Reintentar páginas previamente inaccesibles
python extractor.py --retry-failed
```

El modo `--whisper` puede descargar modelos en su primer uso y necesita espacio en disco; no es necesario para videos con subtítulos. `--frames` descarga temporalmente archivos de video antes de eliminar el original (salvo `--keep-videos`). Puede requerir bastante espacio.

## Archivos de salida

```text
export_pde/
  initial_catalog.json           # 13 actividades confirmadas del HTML semilla
  initial_catalog.csv
  crawl_state.json               # avance y estado de URLs para reanudar
  coverage_report.json           # estado REAL, problemas y enlaces pendientes
  all_activities.csv             # actividades descubiertas por página
  all_links.csv                  # enlaces externos (incluidos artículos)
  all_image_urls.csv             # URLs de recursos gráficos
  images_manifest.json           # estado de descargas, sólo --download-images
  videos_manifest.json           # transcripciones / fotogramas por video
  pages/
    .../content.md              # texto de páginas a las que se tuvo acceso
    .../metadata.json
    .../screenshot.png           # sólo --page-screenshots
  assets/images/                 # sólo --download-images
  videos/
    VIDEO_ID/transcript.txt
    VIDEO_ID/transcript.json
    VIDEO_ID/*.vtt               # subtítulos obtenidos como respaldo
    VIDEO_ID/frames/interval/*.jpg # cada 10 segundos con --all
    VIDEO_ID/frames/scene/*.jpg    # cambios de escena con --all
    VIDEO_ID/manifest.json
```

Los archivos `*.json` y `*.csv` se pueden importar en otros proyectos o adaptar a una página de estudio con React, Svelte, Astro, etc.

## Cómo interpretar el informe de cobertura

**No se puede garantizar el 100%**: puede haber videos sin subtítulos, lecciones con contenido cargado sólo tras iniciar una actividad, restricciones de licencia, material privado, HTML diferente, errores temporales de red o capítulos no expuestos como enlaces. Por eso el proceso no declara que todo se descargó cuando sólo pudo leer el índice.

- `pages_successful`: páginas con contenido visible procesado (no implica que todos los submódulos estén expuestos).
- `pages_with_issues`: páginas inaccesibles, parciales o con errores.
- `pending_discovered_urls`: enlaces detectados que todavía no se pudieron recorrer.
- `youtube_videos_found` y `youtube_transcripts_obtained`: cobertura de videos detectados.

**Para material que aparece sólo dentro de un reproductor de cursos autenticado**, puede ser necesario exportar el contenido desde la plataforma o navegar a la actividad con tu propia cuenta. Este script no inicia laboratorios, no genera créditos, no modifica el progreso y no resuelve CAPTCHA automáticamente.

## Seguridad y uso responsable

- Usa el programa sólo para materiales que tienes autorización para consultar y guardar. Respeta los términos de Google Skills y YouTube y evita redistribuir los materiales protegidos por derechos de autor.
- No se intenta evadir bloqueos anti-bot, paywalls, cuotas, DRM ni autenticación.
- **No subas** `.google_skills_browser/` a GitHub: guarda tu sesión del navegador. `.gitignore` lo excluye.
- No publiques capturas, Markdown ni otros archivos exportados sin revisar si incluyen información personal, códigos temporales o credenciales de laboratorio.
- El HTML original que adjuntaste contiene información de sesión; **no se incluye en este ZIP**. Sólo se incorpora el catálogo limpio de las 13 actividades.
- El navegador es visible por defecto, con pausas entre páginas (`--delay 2`). Si una cuenta es bloqueada o un servidor responde 403/429, el extractor lo deja registrado sin intentar eludirlo.

## Librerías principales

- [Playwright](https://playwright.dev/python/) para páginas con JavaScript y sesión interactiva.
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) y `markdownify` para extraer estructura y contenido.
- [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) para subtítulos/transcripción cuando estén disponibles.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) para subtítulos y media accesible, cuando el usuario lo autorice.
- FFmpeg para fotogramas (opcional) y [faster-whisper](https://github.com/SYSTRAN/faster-whisper) para transcripción local (opcional).
