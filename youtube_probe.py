"""One-video yt-dlp health check. Does not crawl courses or expose cookies."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from yt_dlp_runner import deno_path, execute, project_python

ROOT = Path(__file__).resolve().parent


def check_output(args, *, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                cwd=str(ROOT), errors='replace')
        return {'ok': result.returncode == 0,
                'detail': ((result.stdout or '') + (result.stderr or ''))[-1200:].strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'detail': str(exc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video-id', default='stj830n-1uE')
    ap.add_argument('--metadata-only', action='store_true',
                    help='No descargar material. Solo comprobar acceso a formatos.')
    args = ap.parse_args()
    if not __import__('re').fullmatch(r'[a-zA-Z0-9_-]{11}', args.video_id):
        ap.error('ID de YouTube inválido')
    folder = ROOT / 'export_pde' / 'yt_dlp_prueba'
    folder.mkdir(parents=True, exist_ok=True)
    print('Python utilizado:', project_python(), flush=True)
    version = check_output([project_python(), '-I', '-m', 'yt_dlp', '--version'])
    print('yt-dlp:', version['detail'], flush=True)
    library = check_output([project_python(), '-I', '-c',
        'import yt_dlp;print(yt_dlp.__file__);print(yt_dlp.version.__version__)'])
    print('Ubicación y versión:', library['detail'], flush=True)
    ejs = check_output([project_python(), '-I', '-c',
        'from importlib.metadata import version;print(version("yt-dlp-ejs"))'])
    print('yt-dlp-ejs:', ejs['detail'], flush=True)
    deno = deno_path()
    deno_status = check_output([deno, '--version']) if deno else {'ok': False, 'detail': 'No disponible'}
    print('Deno:', deno_status['detail'], flush=True)
    url = 'https://www.youtube.com/watch?v=' + args.video_id
    print('Comprobando acceso a un video:', url, flush=True)
    metadata = execute(['--skip-download', '--print', '%(id)s | %(title)s | %(duration_string)s', url],
                       timeout=120, verbose=True)
    print('Metadatos:', 'OK' if metadata.ok else 'ERROR', metadata.reason, flush=True)
    downloaded = None
    if metadata.ok and not args.metadata_only:
        print('Probando descarga de UN video (máximo 360 segundos)...', flush=True)
        download_opts = [
            '--format', 'b[height<=480]/bv*[height<=480]+ba/best',
            '--merge-output-format', 'mp4', '--max-filesize', '250M',
            '--output', str(folder / 'prueba.%(ext)s')]
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            download_opts += ['--ffmpeg-location', get_ffmpeg_exe()]
        except (ImportError, RuntimeError, OSError):
            pass
        downloaded = execute(download_opts + [url], timeout=360, verbose=True)
        print('Descarga:', 'OK' if downloaded.ok else 'ERROR', downloaded.reason, flush=True)
    data = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'video_url': url,
        'python': project_python(), 'yt_dlp_version': version,
        'yt_dlp_module': library, 'ejs': ejs, 'deno': deno_status,
        'metadata': metadata.__dict__,
        'download': downloaded.__dict__ if downloaded else None,
    }
    target = folder / 'diagnostico.json'
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Diagnóstico:', target, flush=True)
    if not (version['ok'] and library['ok'] and ejs['ok'] and deno_status['ok'] and metadata.ok):
        print('El problema no está resuelto: revisa el diagnóstico antes de volver a descargar en lote.', flush=True)
        return 2
    if downloaded is not None and not downloaded.ok:
        return 3
    print('Prueba terminada correctamente.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
