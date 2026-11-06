# Recuperación de las 3 versiones HQ pendientes — Path 16

El extractor ya obtuvo 131/131 **transcripciones originales**. El informe HQ
anterior señalaba 128/131 versiones `large-v3` y tres `missing_local_media`.
Los identificadores detectados a partir del log son:

- `etSDI9eM3QQ`
- `PNsLYHr85Mw`
- `G4UPZOmM7hk`

El código **no** fija estos identificadores: detecta automáticamente los
pendientes en cada `videos_manifest.json`, para funcionar con otras rutas.

## Uso en Windows

```powershell
cd C:\my_drive\Portafolio\google_skills_pde_extractor
# Aplicar patch descargado con git am, sobre el commit que ya incorpora HQ paralelo
.\COMPLETAR_3_HQ_WINDOWS.bat
Get-Content .\export_pde\hq_completion_report.json -Raw
Get-Content .\export_pde\ai_library\index.json -Raw
```

1. Conserva las HQ existentes y **no vuelve a procesarlas**.
2. Busca primero `source.*` local, después medios de `export_paths/path_*/videos/`.
3. Si falta audio, el BAT solicita **solo audio** por yt-dlp con un máximo de
   tres intentos en total y 300 segundos por video. No exporta cookies, no
   cambia IP/proxy ni elude las limitaciones del proveedor.
4. Si YouTube devuelve HTTP 429/`IpBlocked`, deja de efectuar nuevas descargas.
   En tal caso, los videos conservan su **transcripción original**, NO se
   generan archivos HQ falsos. Una vez que el acceso sea legítimamente
   disponible, se puede ejecutar de nuevo.
5. Faster-Whisper reanuda `large-v3` CPU INT8 únicamente en los medios nuevos;
   después se regenera `study_pack_path_16.zip`.

Por defecto, el módulo `complete_hq.py` **no accede a la red** si se ejecuta
sin `--fetch-missing`; el archivo BAT sí lo habilita de forma explícita.

## Diagnóstico y estados

- `export_pde/hq_completion_report.json` registra `hq_complete`, `hq_pending`,
  los IDs pendientes y el resultado de cada intento de recuperar audio.
- `export_pde/hq_upgrade_report.json` informa del procesamiento Whisper.
- `export_pde/ai_library/index.json` muestra cuántos videos usan HQ y cuántos
  usan transcripciones originales.
- **Código 0**: todas las HQ disponibles. **Código 3**: faltan HQ, por ejemplo
  por un 429. **Código 1/2**: fallo de procesamiento/exportación.

El informe general `coverage_report.json` puede seguir diciendo `complete`
porque allí se cuenta disponibilidad de transcripción original, no HQ.

No borres `.google_skills_browser`, `export_pde`, `transcript.json`,
`transcript.txt`, `transcript_hq.*` ni los fotogramas.
