"""Offline HQ transcription. Resume without reprocessing completed media.

Default: ONE persistent CPU Whisper model shared by a small worker pool. This
avoids loading large-v3 once per video. Falls back to the legacy one-video
worker with --legacy; original transcript.* files are never modified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from recover_transcripts import read_json, save_json, pick_media

EVENT_PREFIX = 'PDE_HQ_EVENT:'


def is_finished(folder: Path, model: str) -> bool:
    meta = read_json(folder / 'transcript_hq.json', {})
    txt = folder / 'transcript_hq.txt'
    return (isinstance(meta, dict) and meta.get('model') == model and
            isinstance(meta.get('segments'), list) and bool(meta['segments']) and
            txt.is_file() and txt.stat().st_size > 3)


def cpu_plan(workers='auto', cpu_threads='auto') -> tuple[int, int, int, float | None]:
    """Choose conservative settings. Avoid worker*threads > physical cores.

    Unlike os.cpu_count(), psutil can usually provide physical core count and
    available RAM. When unavailable, default to one worker instead of guessing.
    """
    logical = os.cpu_count() or 2
    physical = max(1, logical // 2)
    mem_gb = None
    try:
        import psutil
        physical = psutil.cpu_count(logical=False) or physical
        mem_gb = psutil.virtual_memory().available / (1024 ** 3)
    except ImportError:
        pass
    if workers == 'auto':
        selected_workers = 2 if physical >= 6 and mem_gb is not None and mem_gb >= 10 else 1
    else:
        selected_workers = int(workers)
        if not 1 <= selected_workers <= 4:
            raise ValueError('--workers admite auto o un valor entre 1 y 4')
    if cpu_threads == 'auto':
        selected_threads = min(8, max(1, physical // selected_workers))
    else:
        selected_threads = int(cpu_threads)
        if not 1 <= selected_threads <= 32:
            raise ValueError('--cpu-threads admite auto o un valor entre 1 y 32')
        if selected_threads * selected_workers > physical:
            print(f'AVISO: {selected_threads * selected_workers} hilos solicitados para '
                  f'{physical} nucleos fisicos; ajustar si va mas lento.', flush=True)
    return selected_workers, selected_threads, physical, mem_gb


def _report(out, manifest, details, model, beam_size, compute_type, *, workers=1,
            cpu_threads=None, interrupted=False, worker_exit=None):
    statuses = [x['status'] for x in details]
    summary = {'at': datetime.now(timezone.utc).isoformat(), 'model': model,
               'device': 'cpu', 'compute_type': compute_type, 'beam_size': beam_size,
               'workers': workers, 'cpu_threads': cpu_threads, 'total': len(manifest),
               'upgraded': statuses.count('upgraded'),
               'already_hq': statuses.count('already_hq'),
               'missing_local_media': statuses.count('missing_local_media'),
               'failed': statuses.count('failed'), 'deferred': statuses.count('deferred'),
               'interrupted': interrupted, 'worker_exit_code': worker_exit,
               'details': details,
               'note': 'Las transcripciones HQ son automaticas y pueden tener errores.'}
    save_json(out / 'hq_upgrade_report.json', summary)
    print('HQ: nuevas={upgraded}; previas={already_hq}; sin fuente local={missing_local_media}; '
          'errores={failed}; aplazadas={deferred}'.format(**summary), flush=True)
    return summary


def _legacy_run(selected, out, model, beam_size, language, compute_type, timeout, runner):
    """Backwards compatible path for external tests and emergency fallback."""
    worker = Path(__file__).with_name('whisper_worker.py').resolve()
    results = {}
    for index, video_id, media, folder in selected:
        print(f'[{index}] HQ {video_id}: {media.name} | {model} CPU/{compute_type}', flush=True)
        command = [sys.executable, '-I', str(worker), str(media), str(folder),
                   '--model', model, '--output-prefix', 'transcript_hq', '--beam-size', str(beam_size),
                   '--language', language, '--compute-type', compute_type]
        try:
            response = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, text=True, errors='replace', timeout=timeout)
            if response.returncode == 0 and is_finished(folder, model):
                results[video_id] = ('upgraded', None)
                print('  Transcripcion HQ guardada; original intacta.', flush=True)
                continue
            error = ((response.stderr or '') + '\n' + (response.stdout or ''))[-2500:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f'{type(exc).__name__}: {exc}'
        results[video_id] = ('failed', error)
        print('  ERROR: modelo individual falló; ver hq_upgrade_report.json', flush=True)
        break
    return results, False, 0


def _batch_run(selected, out, model, beam_size, language, compute_type,
               timeout, workers, cpu_threads, popen_factory=None):
    """Launch one persistent worker; stream completed jobs immediately.

    All output files are committed atomically. Killing the batch worker on
    Ctrl+C cannot erase previously finished transcripts; next run skips them.
    """
    worker = Path(__file__).with_name('whisper_batch_worker.py').resolve()
    jobs = [{'id': vid, 'media': str(media), 'folder': str(folder)}
            for _, vid, media, folder in selected]
    results = {}
    interrupted = False
    worker_exit = None
    popen_factory = popen_factory or subprocess.Popen
    # Temporary job manifest lives in out and is cleaned automatically.
    fd, jobs_path = tempfile.mkstemp(prefix='hq_jobs_', suffix='.json', dir=out)
    proc = None
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fp:
            json.dump(jobs, fp, ensure_ascii=False)
        command = [sys.executable, '-I', str(worker), '--jobs-file', jobs_path,
                   '--model', model, '--beam-size', str(beam_size), '--language', language,
                   '--compute-type', compute_type, '--workers', str(workers),
                   '--cpu-threads', str(cpu_threads)]
        proc = popen_factory(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                            errors='replace', bufsize=1)
        last_progress = time.monotonic()
        for line in proc.stdout:
            line = line.rstrip('\r\n')
            if not line.startswith(EVENT_PREFIX):
                if line.strip():
                    print('  ' + line[-1500:], flush=True)
                continue
            try:
                event = json.loads(line[len(EVENT_PREFIX):])
            except json.JSONDecodeError:
                continue
            event_type = event.get('event')
            if event_type == 'loading_model':
                print(f"Modelo {model}: cargando UNA sola vez con {workers} workers, "
                      f"{cpu_threads} hilos por worker...", flush=True)
            elif event_type == 'model_ready':
                print(f"Modelo cargado. Procesando {len(jobs)} videos en paralelo.", flush=True)
            elif event_type == 'video_ok':
                vid = event.get('id')
                results[vid] = ('upgraded', None)
                last_progress = time.monotonic()
                print(f"[{len(results)}/{len(jobs)}] HQ OK: {vid} (guardado)", flush=True)
            elif event_type == 'video_error':
                vid = event.get('id')
                results[vid] = ('failed', event.get('error', 'error desconocido'))
                last_progress = time.monotonic()
                print(f"HQ ERROR {vid}: {str(event.get('error'))[:250]}", flush=True)
            elif event_type == 'heartbeat':
                elapsed = round(time.monotonic() - last_progress)
                print(f"[ACTIVO] Videos terminados: {len(results)}/{len(jobs)}; "
                      f"sin nueva finalizacion desde hace {elapsed}s", flush=True)
                if timeout and elapsed > timeout:
                    print(f'ERROR: sin videos finalizados en {timeout}s; deteniendo lote.', flush=True)
                    proc.kill()
                    interrupted = True
                    break
            elif event_type == 'fatal':
                print('Fallo al iniciar modelo: ' + str(event.get('error'))[:500], flush=True)
        worker_exit = proc.wait()
    except KeyboardInterrupt:
        interrupted = True
        print('\n[INTERRUMPIDO] Conservando las transcripciones HQ ya guardadas...', flush=True)
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        worker_exit = 130
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        Path(jobs_path).unlink(missing_ok=True)

    # Reconcile against actual files, not only stdout events: a completed worker
    # may finish writing files immediately before Ctrl+C or process termination.
    for _, vid, media, folder in selected:
        if is_finished(folder, model):
            results[vid] = ('upgraded', None)
        elif vid not in results:
            results[vid] = ('deferred' if interrupted else 'failed',
                            None if interrupted else 'Worker finalizo sin archivo HQ completo')
    return results, interrupted, worker_exit


def upgrade(out: Path, *, model='large-v3', beam_size=5, language='auto',
            compute_type='int8', timeout=7200, limit=0, runner=None,
            workers='auto', cpu_threads='auto', legacy=False,
            popen_factory=None) -> int:
    out = out.resolve()
    manifest = read_json(out / 'videos_manifest.json', [])
    if not isinstance(manifest, list) or not manifest:
        raise RuntimeError('Falta videos_manifest.json; usa export_pde existente')
    out.mkdir(parents=True, exist_ok=True)
    if beam_size < 1 or beam_size > 10:
        raise ValueError('--beam-size debe estar entre 1 y 10')
    details = []
    selected = []
    attempts = 0
    # The complete report includes completed, missing and deferred videos.
    for index, item in enumerate(manifest, 1):
        vid = item.get('id') if isinstance(item, dict) else None
        if not isinstance(vid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            continue
        folder = out / 'videos' / vid
        if is_finished(folder, model):
            details.append({'id': vid, 'status': 'already_hq', 'model': model})
            continue
        media = pick_media(folder)
        if not media:
            details.append({'id': vid, 'status': 'missing_local_media', 'model': model})
            continue
        if limit and attempts >= limit:
            details.append({'id': vid, 'status': 'deferred', 'model': model})
            continue
        attempts += 1
        selected.append((index, vid, media, folder))
        details.append({'id': vid, 'status': 'queued', 'model': model})

    chosen_workers, threads, cores, mem = cpu_plan(workers, cpu_threads)
    print(f'CPU detectada: {cores} nucleos fisicos aprox.; RAM disponible: '
          f'{mem:.1f} GB' if mem is not None else
          f'CPU detectada: {cores} nucleos fisicos aprox.; RAM no disponible', flush=True)
    print(f'Configuracion HQ: workers={chosen_workers}, cpu_threads={threads}, '
          f'modelo={model}, pendientes de este lote={len(selected)}.', flush=True)

    if not selected:
        summary = _report(out, manifest, details, model, beam_size, compute_type,
                          workers=chosen_workers, cpu_threads=threads)
        return 0 if not summary['failed'] else 1
    if runner is not None or legacy:
        results, interrupted, exit_code = _legacy_run(
            selected, out, model, beam_size, language, compute_type, timeout,
            runner or subprocess.run)
    else:
        results, interrupted, exit_code = _batch_run(
            selected, out, model, beam_size, language, compute_type,
            timeout, chosen_workers, threads, popen_factory=popen_factory)
    # Always reflect saved files, including success after receiving Ctrl+C.
    for entry in details:
        if entry['status'] != 'queued':
            continue
        vid = entry['id']
        state, error = results.get(vid, ('deferred' if interrupted else 'failed', None))
        entry['status'] = state
        if error:
            entry['error'] = error
    summary = _report(out, manifest, details, model, beam_size, compute_type,
                      workers=chosen_workers, cpu_threads=threads,
                      interrupted=interrupted, worker_exit=exit_code)
    return 130 if interrupted else (1 if summary['failed'] else 0)


def main() -> int:
    p = argparse.ArgumentParser(description='Transcribir videos locales con Whisper HQ paralelo y reanudable')
    p.add_argument('--out', type=Path, default=Path('export_pde'))
    p.add_argument('--model', default='large-v3')
    p.add_argument('--beam-size', type=int, default=5)
    p.add_argument('--language', default='auto')
    p.add_argument('--compute-type', choices=['int8', 'float32'], default='int8')
    p.add_argument('--timeout', type=int, default=7200,
                   help='Segundos maximos sin FINALIZAR un video; 0 desactiva vigilancia')
    p.add_argument('--limit', type=int, default=1,
                   help='1 para prueba; 0 procesa todos los videos pendientes')
    p.add_argument('--workers', default='auto',
                   help='auto o 1-4: videos concurrentes sobre un SOLO modelo')
    p.add_argument('--cpu-threads', default='auto',
                   help='auto o 1-32: hilos por worker; evite superar nucleos fisicos')
    p.add_argument('--legacy', action='store_true',
                   help='Usar un proceso por video (modo anterior, mas lento)')
    args = p.parse_args()
    try:
        return upgrade(args.out, model=args.model, beam_size=args.beam_size,
                       language=args.language, compute_type=args.compute_type,
                       timeout=max(0, args.timeout), limit=max(0, args.limit),
                       workers=args.workers, cpu_threads=args.cpu_threads,
                       legacy=args.legacy)
    except (OSError, RuntimeError, ValueError) as exc:
        print('ERROR:', exc, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
