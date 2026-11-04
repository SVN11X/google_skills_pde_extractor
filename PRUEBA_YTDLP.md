# Diagnóstico puntual yt-dlp / YouTube

El error `The page needs to be reloaded` ya se ha observado en versiones recientes del extractor de YouTube. La documentación de yt-dlp recomienda instalar `yt-dlp[default]` (incluye EJS) y Deno 2.3+; según la situación puede funcionar el cliente `default,web_embedded`. Estas configuraciones **no garantizan** que YouTube entregue el video, ni evaden videos privados o con DRM.

## En Windows

1. Cierra otras ejecuciones del extractor.
2. Haz doble clic en **`PROBAR_YTDLP_WINDOWS.bat`**.
3. El script actualizará `yt-dlp[default]` **dentro de `.venv`** y comprobará Deno.
4. Probará un solo video de la lista, sin recorrer Google Skills.
5. Si indica `Prueba terminada correctamente`, vuelve a usar `CONTINUAR_SEGURO_WINDOWS.bat` para el lote.
6. Si falla, comparte `export_pde/yt_dlp_prueba/diagnostico.json`, ocultando cualquier dato que consideres privado.

La prueba en realidad intenta bajar **un video a 480p** para comprobar la etapa necesaria para las capturas, no solo consultar metadatos. Puedes ejecutar la comprobación solo de formatos mediante:

```powershell
.\.venv\Scripts\python.exe youtube_probe.py --video-id stj830n-1uE --metadata-only
```

Al trabajar sobre un único video se evitan cientos de solicitudes fallidas. El flujo normal de extracción también usa ahora un proceso `yt-dlp` aislado, sin configuración o cookies de yt-dlp heredadas, con tiempos máximos: 120 segundos por subtítulos y 420 segundos por descarga de video. Los fallos se registran y el lote puede continuar sin lanzar una excepción no capturada.

**No elimines `export_pde` ni `.google_skills_browser`.** Los videos cuya descarga falle no tendrán frames y no deben considerarse completados. No publiques datos de sesión ni exportaciones privadas en GitHub.

Referencia: https://github.com/yt-dlp/yt-dlp/wiki/EJS
