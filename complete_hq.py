"""Complete only missing Whisper HQ results, safely reusing local Google Skills media.

No crawling, login or browser profile access. Network is OFF by default; explicitly
pass --fetch-missing to request audio for missing videos with yt-dlp. Stop on 429.
The existing transcript and frames files are never overwritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import time

from recover_transcripts import pick_media, read_json, save_json
from upgrade_transcripts import is_finished, upgrade

VID_PATTERN = re.compile(r'[A-Za-z0-9_-]{11}\Z')
RATE_LIMIT_RE = re.compile(r'(?:\b429\b|too many requests|rate.?limit|ipblocked|ip.blocked)', re.I)


def videos_from_manifest(out: Path) -> list[str]:
    records = read_json(out / 'videos_manifest.json', [])
    if not isinstance(records, list) or not records:
        raise RuntimeError('Falta videos_manifest.json; no se pueden determinar los videos')
    found = []
    for entry in records:
        vid = entry.get('id') if isinstance(entry, dict) else None
        if isinstance(vid, str) and VID_PATTERN.fullmatch(vid) and vid not in found:
            found.append(vid)
    if not found:
        raise RuntimeError('El manifiesto no tiene identificadores de video válidos')
    return found


def locate_reusable_media(out: Path, vid: str, external_roots=()) -> Path | None:
    """Look in sibling multipath archives; never scan arbitrary directories."""
    roots = [out.parent / 'export_paths', *external_roots]
    if out.parent.name == 'export_paths':
        roots.insert(0, out.parent)
    unique = set()
    for base in roots:
        base = Path(base)
        if str(base.resolve()) in unique:
            continue
        unique.add(str(base.resolve()))
        for folder in sorted(base.glob('path_*/videos/' + vid)):
            candidate = pick_media(folder)
            if candidate:
                return candidate
    return None


def copy_reusable_media(source: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / ('source' + source.suffix.lower())
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    temp = folder / ('source_copy' + source.suffix.lower() + '.tmp')
    try:
        shutil.copyfile(source, temp)
        if temp.stat().st_size < 1024:
            raise OSError('La copia local está vacía')
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)
    return dest


def fetch_audio(video_id: str, folder: Path, *, timeout=300, execute_fn=None):
    """Request only the audio stream; no browser credentials or proxy rotation."""
    if not VID_PATTERN.fullmatch(video_id):
        raise ValueError('Identificador de video inválido')
    existing = pick_media(folder)
    if existing:
        return existing, ''
    folder.mkdir(parents=True, exist_ok=True)
    if execute_fn is None:
        from yt_dlp_runner import execute as execute_fn
    # yt_dlp_runner already selects project .venv, Deno and bounded retries.
    params = ['--format', 'bestaudio[ext=m4a]/bestaudio/best',
              '--output', str(folder / 'source.%(ext)s'), '--continue',
              '--no-overwrites', '--no-progress', '--max-filesize', '500M',
              f'https://www.youtube.com/watch?v={video_id}']
    outcome = execute_fn(params, timeout=timeout)
    media = pick_media(folder)
    if not outcome.ok:
        return None, outcome.reason or 'yt-dlp no pudo obtener el audio'
    if not media:
        return None, 'yt-dlp salió correctamente pero no produjo un source.* utilizable'
    return media, ''


def status_report(out: Path, video_ids: list[str], model: str, outcomes: list[dict]) -> dict:
    hq_ids = [vid for vid in video_ids if is_finished(out / 'videos' / vid, model)]
    missing = [vid for vid in video_ids if vid not in hq_ids]
    available_original = [vid for vid in video_ids
                          if (out / 'videos' / vid / 'transcript.txt').is_file()]
    report = {
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model': model, 'total_videos': len(video_ids),
        'hq_complete': len(hq_ids), 'hq_pending': len(missing),
        'hq_pending_ids': missing, 'original_transcripts_available': len(available_original),
        'status': 'complete' if not missing else 'partial',
        'media_recovery': outcomes,
        'note': 'HQ pendiente no significa transcripción original ausente; no se inventan resultados HQ.',
    }
    save_json(out / 'hq_completion_report.json', report)
    return report


def complete(out: Path, *, model='large-v3', fetch_missing=False,
             max_downloads=3, download_timeout=300, wait_seconds=8,
             workers='auto', cpu_threads='auto', media_roots=(),
             execute_fn=None, upgrader=upgrade, corpus_builder=None,
             sleep_fn=time.sleep) -> int:
    out = out.resolve()
    video_ids = videos_from_manifest(out)
    missing = [v for v in video_ids if not is_finished(out / 'videos' / v, model)]
    print(f'HQ existentes: {len(video_ids)-len(missing)}/{len(video_ids)}; '
          f'pendientes: {len(missing)}.', flush=True)
    if missing:
        print('Videos sin versión HQ: ' + ', '.join(missing), flush=True)
    outcomes = []
    downloads = 0
    blocked = False
    for vid in missing:
        folder = out / 'videos' / vid
        if pick_media(folder):
            outcomes.append({'id': vid, 'media': 'local', 'status': 'ready'})
            continue
        reusable = locate_reusable_media(out, vid, media_roots)
        if reusable:
            try:
                copy_reusable_media(reusable, folder)
                outcomes.append({'id': vid, 'media': 'other_local_path', 'status': 'ready'})
                print(f'{vid}: audio/video reutilizado desde otra ruta local', flush=True)
                continue
            except OSError as exc:
                print(f'{vid}: no se pudo copiar la fuente local: {exc}', flush=True)
        if not fetch_missing:
            outcomes.append({'id': vid, 'status': 'missing_media', 'reason': 'descarga desactivada'})
            continue
        if blocked:
            outcomes.append({'id': vid, 'status': 'skipped_after_rate_limit'})
            continue
        if downloads >= max_downloads:
            outcomes.append({'id': vid, 'status': 'download_limit_reached'})
            continue
        if downloads and wait_seconds:
            sleep_fn(wait_seconds)
        downloads += 1
        print(f'[{downloads}/{max_downloads}] Descargando SOLO audio: {vid}', flush=True)
        media, error = fetch_audio(vid, folder, timeout=download_timeout, execute_fn=execute_fn)
        if media:
            outcomes.append({'id': vid, 'status': 'audio_downloaded', 'media': media.name})
            print(f'  Audio disponible: {media.name}', flush=True)
        else:
            redacted = (error or 'error desconocido')[-400:]
            status = 'rate_limited' if RATE_LIMIT_RE.search(redacted) else 'download_failed'
            outcomes.append({'id': vid, 'status': status, 'reason': redacted})
            print(f'  No se recuperó audio: {redacted}', flush=True)
            if status == 'rate_limited':
                blocked = True
                print('  YouTube limitó solicitudes. No se intentarán más descargas.', flush=True)

    # Safe resume: only uncompleted HQ files for which source.* exists are queued.
    result = upgrader(out, model=model, workers=workers, cpu_threads=cpu_threads,
                      beam_size=5, compute_type='int8', limit=0)
    final = status_report(out, video_ids, model, outcomes)
    print(f"HQ FINAL: {final['hq_complete']}/{final['total_videos']}; "
          f"pendientes={final['hq_pending']}; estado={final['status']}", flush=True)
    if corpus_builder is None:
        from build_ai_corpus import build as corpus_builder
    try:
        corpus_builder(out)
        print('Biblioteca para IA actualizada. No se alteraron los originales.', flush=True)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ERROR al exportar para IA: {exc}', flush=True)
        return 2
    if result:
        return result
    return 0 if final['status'] == 'complete' else 3


def main() -> int:
    p = argparse.ArgumentParser(description='Recuperar HQ pendientes con medios locales o audio selectivo')
    p.add_argument('--out', type=Path, default=Path('export_pde'))
    p.add_argument('--model', default='large-v3')
    p.add_argument('--fetch-missing', action='store_true', help='Permitir descargar SOLO audios de videos sin HQ ni medio local')
    p.add_argument('--max-downloads', type=int, default=3)
    p.add_argument('--download-timeout', type=int, default=300)
    p.add_argument('--wait-seconds', type=int, default=8)
    p.add_argument('--media-root', action='append', type=Path, default=[])
    p.add_argument('--workers', default='auto')
    p.add_argument('--cpu-threads', default='auto')
    args = p.parse_args()
    if args.max_downloads < 0 or args.download_timeout < 10 or args.wait_seconds < 0:
        p.error('max-downloads >= 0, download-timeout >= 10 y wait-seconds >= 0 son obligatorios')
    try:
        return complete(args.out, model=args.model, fetch_missing=args.fetch_missing,
                        max_downloads=args.max_downloads, download_timeout=args.download_timeout,
                        wait_seconds=args.wait_seconds, media_roots=args.media_root,
                        workers=args.workers, cpu_threads=args.cpu_threads)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
