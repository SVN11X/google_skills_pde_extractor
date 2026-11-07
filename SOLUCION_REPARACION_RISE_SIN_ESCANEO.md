# Reparacion Rise Path 16: evita recorrer todas las paginas

Este parche se aplica **despues** de `GoogleSkills_PATH16_REPARACION_VISUAL_RISE_REGENERADO_V2_20261107.patch`.

## Problema corregido

El modo `--repair-screenshots` llamaba a `page_resources(out)` antes de filtrar las 13 lecciones pendientes. Esto abria los metadatos de todas las paginas, incluso cuando `rise_deep_manifest.json` ya contenia las rutas exactas. El `KeyboardInterrupt` del registro significa que el proceso se interrumpio manualmente durante esa lectura; no indica corrupcion.

## Cambio

En modo de reparacion, `deep_capture_path16.py` usa `rise_deep_manifest.json`, valida rutas y archivos, y abre solo las lecciones cuyo numero de estados supera las capturas de pantalla. Para la extraccion normal y la revision inicial de cuestionarios se mantiene el funcionamiento anterior.

## Instrucciones de Windows PowerShell

```powershell
cd C:\my_drive\Portafolio\google_skills_pde_extractor
git status
git pull --ff-only origin main
git am "$env:USERPROFILE\Downloads\GoogleSkills_PATH16_RISE_REPARACION_RAPIDA_20261107_git_am.patch"
.\REPARAR_EVIDENCIA_VISUAL_RISE_PATH16_WINDOWS.bat
```

La salida deberia comenzar con algo parecido a:

```text
[AUDITORÍA] Reparación visual selectiva: 13 de 13 lecciones pendientes (sin recorrer metadatos de todas las páginas)
[1/13] INSPECCIONANDO: ...
```

Al terminar, revisar:

```powershell
$r = Get-Content '.\export_pde\rise_deep_gap_audit.json' -Raw | ConvertFrom-Json
$r.summary | Select-Object unpictured_states, lessons_with_unpictured_states, screenshots_saved
```

Si el resultado mejora y no aparecen errores:

```powershell
git push origin main
```

**Conservacion:** no se borran ni se sobrescriben las capturas de una leccion a menos que el nuevo intento tenga mas imagenes y al menos tanta evidencia como antes. Los originales reemplazados se respaldan bajo `rise_deep_prev`. No se inician cuestionarios ni se transcriben videos. Esta modificacion no garantiza que `unpictured_states` llegue a cero si hay errores de red o capturas fallidas.

**Importante:** no apliques dos veces el parche. Si el navegador no permite bajar `.patch`, usa el ZIP o aplica su copia `.txt` con `git am`.
