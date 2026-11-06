# HQ parallel / Windows (Google Skills PDE)

## Por qué era lento

El modo anterior ejecutaba `whisper_worker.py` una vez por cada video, y cada
subproceso cargaba `large-v3` desde cero. Este parche reemplaza esa ruta por un
único proceso con un modelo residente de Faster-Whisper y `num_workers` para
atender varios archivos a la vez. El modelo se mantiene en **CPU INT8** y
`beam_size=5`; no se sacrifica deliberadamente calidad para acelerar.

**No promete un factor de aceleración fijo.** El rendimiento depende del número
de núcleos físicos, RAM disponible, duración de los videos y velocidad del
almacenamiento. Más workers no siempre es más rápido; el exceso de hilos suele
empeorarlo.

## Prueba de dos videos pendientes

```powershell
.\MEJORAR_TRANSCRIPCIONES_WINDOWS.bat
```

O directamente, desde la raíz con `.venv`:

```powershell
.\.venv\Scripts\python.exe -u upgrade_transcripts.py --out export_pde --model large-v3 --workers auto --cpu-threads auto --limit 2
```

El modo auto limita la concurrencia a 1 o 2 según núcleos físicos y memoria
libre. Si tu ordenador tiene suficientes recursos puedes experimentar con:

```powershell
.\.venv\Scripts\python.exe -u upgrade_transcripts.py --out export_pde --model large-v3 --workers 2 --cpu-threads 4 --limit 0
```

En un equipo modesto, usa `--workers 1 --cpu-threads 4`. En un equipo de 12 o
más núcleos físicos y RAM suficiente puedes comparar `--workers 3 --cpu-threads 4`.
Evita que `workers * cpu_threads` supere el número de núcleos físicos.

## Reanudación, registro y seguridad

- Todo el trabajo es **local** sobre `export_pde/videos/<video-id>/source.*`.
- No abre Chrome ni consume cuotas de YouTube.
- Salta los archivos `transcript_hq.json` + `transcript_hq.txt` completos del
  mismo modelo, por lo que **no vuelve a transcribir** lo terminado.
- Mantiene intactos `transcript.json` y `transcript.txt` originales.
- Cada par HQ se escribe con reemplazo atómico.
- El progreso y los errores quedan en `export_pde/hq_upgrade_report.json`.
- Si interrumpes con Ctrl+C, los archivos HQ guardados se preservan.
- Emite un mensaje `[ACTIVO]` periódicamente aunque todavía no haya finalizado
  un video. Esto indica que el proceso está vivo, no necesariamente que avance.
- `--timeout` limita el tiempo sin terminar nuevos videos, no el tiempo total.
- Si un video falla, el lote sigue con los demás y queda registrado en el
  informe. Puedes volver a ejecutar el mismo comando.

Después de completar el lote actualiza el paquete para IA:

```powershell
.\EXPORTAR_PARA_IA_WINDOWS.bat
```

## Alternativa de compatibilidad

Si tu plataforma presenta problemas con el motor concurrente, fuerza el modo
anterior, más lento:

```powershell
.\.venv\Scripts\python.exe -u upgrade_transcripts.py --out export_pde --model large-v3 --limit 0 --legacy
```

## Nota importante de calidad

Las transcripciones con ASR siguen pudiendo equivocarse. El sistema indica
qué modelo produjo cada segmento y conserva la fuente audiovisual para cotejar.
