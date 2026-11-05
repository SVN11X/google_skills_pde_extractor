"""Optional OFFLINE quality upgrade; preserves all original transcript.* files.

Requires source.* media from previous extraction. Never opens Chrome, downloads
YouTube media, or modifies the original transcripts/coverage metrics.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone

from recover_transcripts import read_json, save_json, pick_media


def is_finished(folder: Path, model: str) -> bool:
    meta = read_json(folder / 'transcript_hq.json', {})
    text = folder / 'transcript_hq.txt'
    return (isinstance(meta, dict) and meta.get('model') == model and
            isinstance(meta.get('segments'), list) and bool(meta['segments']) and
            text.is_file() and text.stat().st_size > 3)


def upgrade(out: Path, *, model='large-v3', beam_size=5, language='auto',
            compute_type='int8', timeout=7200, limit=0, runner=None) -> int:
    out = out.resolve()
    manifest = read_json(out / 'videos_manifest.json', [])
    if not isinstance(manifest, list) or not manifest:
        raise RuntimeError('Falta videos_manifest.json; usa el directorio export_pde existente')
    worker = Path(__file__).with_name('whisper_worker.py').resolve()
    runner = runner or subprocess.run
    details = []
    attempts = 0
    for index, item in enumerate(manifest, 1):
        video_id = item.get('id')
        if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            continue
        folder = out / 'videos' / video_id
        if is_finished(folder, model):
            details.append({'id': video_id, 'status': 'already_hq', 'model': model})
            continue
        media = pick_media(folder)
        if not media:
            details.append({'id': video_id, 'status': 'missing_local_media', 'model': model})
            continue
        if limit and attempts >= limit:
            details.append({'id': video_id, 'status': 'deferred', 'model': model})
            continue
        attempts += 1
        print(f'[{index}/{len(manifest)}] HQ {video_id}: {media.name} | {model} CPU/{compute_type}', flush=True)
        command = [sys.executable, '-I', str(worker), str(media), str(folder),
                   '--model', model, '--output-prefix', 'transcript_hq', '--beam-size', str(beam_size),
                   '--language', language, '--compute-type', compute_type]
        try:
            result = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, errors='replace', timeout=timeout)
            if result.returncode == 0 and is_finished(folder, model):
                details.append({'id': video_id, 'status': 'upgraded', 'model': model})
                print('  Transcripción HQ guardada; original intacta.', flush=True)
                continue
            error = ((result.stderr or '') + '\n' + (result.stdout or ''))[-2500:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f'{type(exc).__name__}: {exc}'
        details.append({'id': video_id, 'status': 'failed', 'model': model, 'error': error})
        # Stop on first failure to avoid repeating a model setup error dozens of times.
        print('  ERROR: se detuvo para evitar fallos repetidos. Ver hq_upgrade_report.json', flush=True)
        break
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'model': model,
               'device': 'cpu', 'compute_type': compute_type, 'beam_size': beam_size,
               'total': len(manifest), 'upgraded': sum(x['status']=='upgraded' for x in details),
               'already_hq': sum(x['status']=='already_hq' for x in details),
               'missing_local_media': sum(x['status']=='missing_local_media' for x in details),
               'failed': sum(x['status']=='failed' for x in details),
               'deferred': sum(x['status']=='deferred' for x in details), 'details': details,
               'note': 'El estado complete de la extracción original NO prueba exactitud ni calidad HQ.'}
    save_json(out / 'hq_upgrade_report.json', summary)
    print('HQ: nuevas={upgraded}; previas={already_hq}; sin fuente local={missing_local_media}; '
          'errores={failed}; aplazadas={deferred}'.format(**summary), flush=True)
    return 1 if summary['failed'] else 0


def main() -> int:
    p = argparse.ArgumentParser(description='Mejorar transcripciones locales sin sobrescribir originales')
    p.add_argument('--out', type=Path, default=Path('export_pde'))
    p.add_argument('--model', default='large-v3')
    p.add_argument('--beam-size', type=int, default=5)
    p.add_argument('--language', default='auto')
    p.add_argument('--compute-type', choices=['int8', 'float32'], default='int8')
    p.add_argument('--timeout', type=int, default=7200)
    p.add_argument('--limit', type=int, default=1,
                   help='Comenzar con 1 video para validar el modelo; 0 procesa todos los disponibles')
    args = p.parse_args()
    try:
        return upgrade(args.out, model=args.model, beam_size=args.beam_size,
                       language=args.language, compute_type=args.compute_type,
                       timeout=args.timeout, limit=max(0, args.limit))
    except (OSError, RuntimeError, ValueError) as exc:
        print('ERROR:', exc, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
