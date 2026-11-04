# Corrección del cierre por CUDA/cuDNN de Faster-Whisper

## Diagnóstico

El registro del 4 de noviembre de 2026 confirma que yt-dlp ya descarga videos y
FFmpeg genera fotogramas. Al procesar `UdtAa7t--n0`, Faster-Whisper con
`device='auto'` intentaba cargar CUDA/cuDNN y el proceso Windows terminaba
con el código `3221226505`, después de indicar que faltaba
`cudnn_ops64_9.dll`.

## Cambios

- Whisper ahora se ejecuta en un **subproceso** con `device='cpu'` y
  `compute_type='int8'`, sin depender de CUDA, GPU NVIDIA ni cuDNN.
- Un cierre nativo o un timeout de Whisper no termina el scraper completo:
  el video queda como pendiente y se continúa con el siguiente.
- Los videos con transcripción y capturas completas se omiten en reanudaciones.
- Los medios descargados se conservan si falta una salida solicitada, para
  que el siguiente intento no los descargue otra vez.
- Los resultados se guardan de forma atómica.

## Instalación

1. Detén las instancias previas de la herramienta.
2. En la rama `main`, aplica el parche `git am ...patch` o copia los archivos
   `extractor.py` y `whisper_worker.py` sobre la carpeta del proyecto.
3. **NO borres** `export_pde`, `.google_skills_browser`, `.venv` ni `.tools`.
4. Ejecuta `CONTINUAR_SEGURO_WINDOWS.bat` como antes. No hay un nuevo BAT.

Para verificar offline (con las dependencias instaladas):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

En consola deberías ver `Whisper local en CPU INT8` cuando necesite
transcribir un video sin subtítulos. La CPU puede tardar más que la GPU, pero
es compatible con equipos que no tienen cuDNN configurado.

## Alcance

No se ha validado la transcripción de los 131 videos usando la conexión del
usuario. La corrección es específica del cierre por cuDNN; no garantiza acceso
a contenidos restringidos ni que todos los videos tengan pistas de audio.
