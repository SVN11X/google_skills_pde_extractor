"""Recover missing video transcripts from local media only; never launches Chrome.

Stops immediately on the first systemic Whisper failure, with the full worker
error saved in export_pde/whisper_recovery_diagnostic.txt. This prevents a
repetition of a 131-video run when the speech engine is misconfigured.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def valid_transcript(folder: Path) -> bool:
    text = folder / 'transcript.txt'
    return text.exists() and text.is_file() and text.stat().st_size > 3


def pick_media(folder: Path) -> Path | None:
    media_extensions = {'.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.opus', '.ogg', '.wav', '.mov', '.ts', '.aac', '.flac'}
    choices = [p for p in folder.glob('source.*') if p.is_file()
               and p.suffix.lower() in media_extensions and p.stat().st_size > 1024]
    return max(choices, key=lambda p: p.stat().st_size) if choices else None


def recover(out: Path, *, model: str = 'small', timeout: int = 1800, runner=None):
    out = out.resolve()
    manifest_path = out / 'videos_manifest.json'
    items = read_json(manifest_path, None)
    if not isinstance(items, list) or not items:
        raise RuntimeError('No existe videos_manifest.json con videos para recuperar.')
    worker = Path(__file__).with_name('whisper_worker.py').resolve()
    if not worker.is_file():
        raise RuntimeError('Falta whisper_worker.py en la carpeta del proyecto.')
    runner = runner or subprocess.run
    stats = dict(total=len(items), already_ok=0, recovered=0, missing_media=0,
                 failed=0, attempts=0)
    diagnostic = out / 'whisper_recovery_diagnostic.txt'
    # Fresh diagnostic per invocation, do not expose browser profile or cookies.
    diagnostic.unlink(missing_ok=True)
    for index, item in enumerate(items, 1):
        video_id = item.get('id')
        if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            continue
        folder = out / 'videos' / video_id
        if valid_transcript(folder):
            item['transcript'] = 'ok'
            stats['already_ok'] += 1
            continue
        media = pick_media(folder)
        if not media:
            stats['missing_media'] += 1
            print(f'[{index}/{len(items)}] {video_id}: no hay video/audio local; no se descargará nuevamente.', flush=True)
            continue
        stats['attempts'] += 1
        print(f'[{index}/{len(items)}] Probando Whisper CPU INT8: {video_id} ({media.name})', flush=True)
        command = [sys.executable, '-I', str(worker), str(media), str(folder), '--model', model]
        try:
            result = runner(command, capture_output=True, text=True, errors='replace',
                            stdin=subprocess.DEVNULL, timeout=timeout)
            err = (result.stderr or '') + '\n' + (result.stdout or '')
            passed = result.returncode == 0 and valid_transcript(folder)
            code = result.returncode
        except subprocess.TimeoutExpired as exc:
            err, passed, code = f'Whisper superó el límite de {timeout} segundos: {exc}', False, 124
        except OSError as exc:
            err, passed, code = f'No se pudo iniciar Whisper: {type(exc).__name__}: {exc}', False, 126
        if passed:
            item['transcript'] = 'ok'
            item['transcription_recovered_locally'] = True
            item['checked_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            stats['recovered'] += 1
            per_video = folder / 'manifest.json'
            data = read_json(per_video, {})
            if isinstance(data, dict):
                data.update(transcript='ok', transcription_recovered_locally=True, checked_at=item['checked_at'])
                save_json(per_video, data)
            save_json(manifest_path, items)
            print('  Transcripción recuperada correctamente.', flush=True)
        else:
            stats['failed'] += 1
            reason = f'Whisper falló en video {video_id} con código {code}.\n\n{err.strip()}\n'
            diagnostic.write_text(reason, encoding='utf-8')
            print('  ERROR: consulta ' + str(diagnostic), flush=True)
            print(reason[-3500:], flush=True)
            # Fail-fast to avoid reprocessing 88 other videos with same broken configuration.
            break
    save_json(manifest_path, items)
    pending = [i.get('url') for i in items if i.get('transcript') != 'ok']
    report_path = out / 'coverage_report.json'
    report = read_json(report_path, {})
    if not isinstance(report, dict):
        report = {}
    report.update(youtube_videos_found=len(items),
                  youtube_transcripts_obtained=len(items) - len(pending),
                  youtube_transcripts_pending=len(pending),
                  youtube_videos_without_transcription=pending,
                  completion_status='partial' if pending else 'complete')
    save_json(report_path, report)
    stats['still_pending'] = len(pending)
    save_json(out / 'whisper_recovery_summary.json', stats)
    print(f"RESUMEN: recuperadas={stats['recovered']}, ya listas={stats['already_ok']}, "
          f"sin medio local={stats['missing_media']}, fallos={stats['failed']}, "
          f"transcripciones pendientes={len(pending)}", flush=True)
    return 1 if stats['failed'] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Recuperar transcripciones locales sin navegar ni redescargar.')
    parser.add_argument('--out', type=Path, default=Path('export_pde'))
    parser.add_argument('--model', default='small')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    try:
        return recover(args.out, model=args.model, timeout=args.timeout)
    except (OSError, RuntimeError) as exc:
        print('ERROR: ' + str(exc), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
