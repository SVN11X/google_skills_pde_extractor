# Google Skills: transcripción de alta calidad + múltiples rutas + biblioteca para IA

## Antes de usarlo

- El extractor anterior utilizaba Whisper **small**, CPU INT8. El recuento 131/131 refleja cobertura de texto, **no** exactitud de las palabras.
- La mejora seleccionada es **Whisper large-v3** (Faster-Whisper, CPU INT8, `beam_size=5`). El modelo es significativamente más grande y lento que `small`; su primera ejecución necesita descargar los pesos. No se utiliza CUDA/cuDNN.
- Whisper large-v3 **no siempre** supera a otros sistemas (por ejemplo Qwen3-ASR 1.7B) en cada idioma o acústica. No se garantiza una transcripción perfecta; compara con el audio y los subtítulos cuando sea posible.
- **No se alteran** `export_pde`, las transcripciones originales, el perfil `.google_skills_browser` ni las capturas. La mejora escribe `transcript_hq.*` como nueva variante.
- El modo de mejora no usa red para descargar videos, pero **sí puede descargar el modelo** durante su primera ejecución; posteriormente utiliza el modelo en caché.

## 1. Mejora de las transcripciones existentes (opcional)

Primero prueba un solo video:

```powershell
.\MEJORAR_TRANSCRIPCIONES_WINDOWS.bat
```

Después, para todos los videos **con archivos `source.*` conservados**:

```powershell
.\.venv\Scripts\python.exe upgrade_transcripts.py --out export_pde --model large-v3 --beam-size 5 --limit 0
```

Resultado: `export_pde/videos/ID/transcript_hq.json`, `transcript_hq.txt` y `export_pde/hq_upgrade_report.json`. Si no hay audio o video local, se reporta `missing_local_media` sin volver a descargarlo. **Una transcripción original válida nunca se borra.**

Si tienes varios idiomas, el detector automático ayuda; para forzar inglés utiliza `--language en` en el comando `upgrade_transcripts.py`.

## 2. Biblioteca organizada para una IA

```powershell
.\EXPORTAR_PARA_IA_WINDOWS.bat
```

Se genera:

- `export_pde/ai_library/study_corpus.jsonl`: fragmentos con URL, ruta, modelo, origen y segundos de video.
- `export_pde/ai_library/study_corpus.md`: lectura sencilla por una IA.
- `export_pde/ai_library/study_pack_path_16.zip`: paquete de textos listo para compartir, **sin** cookies ni perfil de Chrome.
- `export_pde/ai_library/INSTRUCCIONES_IA.md`: instrucciones para estudiar, comparar y pedir preguntas con citas verificables.

El archivo `.jsonl` contiene metadatos para construir un índice vectorial o RAG posteriormente. **No incluye un motor de búsqueda vectorial**: es la base de datos estructurada para crearlo.

La exportación favorece `transcript_hq.json` si existe, y usa `transcript.json` como respaldo. Las rutas a fotogramas se registran como referencias locales; el ZIP de estudio contiene texto y metadatos, **no** las imágenes binarias.

## 3. Varios paths (sin mezclar datos)

Edita `paths.txt`: agrega una URL `https://www.skills.google/paths/NUMERO` por línea.

```powershell
.\MULTIPATH_WINDOWS.bat
```

Alternativa sin navegador para bibliotecas ya extraídas:

```powershell
.\.venv\Scripts\python.exe multi_path.py --paths-file paths.txt --mode ai-only
```

Las exportaciones nuevas van a `export_paths/path_NUMERO` y usan el perfil local de Chrome compartido secuencialmente. Se mantiene el directorio histórico `export_pde` de la ruta 16. Si la ruta 16 aparece en `paths.txt` y ya existe `export_pde/videos_manifest.json`, el multipath la reutiliza directamente, crea su biblioteca para IA y la incluye en la colección combinada, sin volver a recorrerla. Cada path debe ser accesible a tu sesión sin eludir restricciones ni mecanismos de acceso.

La biblioteca combinada se genera en `export_paths/combined_ai_library/study_corpus.jsonl`.

## 4. Verificación y cuidados

- Selecciona al menos 5–10 videos, con distintos acentos y palabras técnicas, y compara manualmente sus resultados `small` vs `large-v3` y contra el audio real.
- Para lecciones evaluadas, **no uses una transcripción automática como autoridad definitiva**; verifica la documentación oficial y la fecha del servicio de Google Cloud.
- No publiques archivos del perfil, cookies, claves, credenciales temporales de laboratorios ni contenido privado en GitHub. Los archivos preparados son para uso personal autorizado.
- Si el equipo no tiene RAM/CPU suficiente, prueba `--model turbo` (si es compatible con tu versión de Faster-Whisper) o conserva `small`; la diferencia entre velocidad y exactitud debe medirse en tu equipo.
