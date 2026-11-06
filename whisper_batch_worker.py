"""One resident Faster-Whisper model, bounded concurrent CPU transcriptions.

Invoked only as an isolated subprocess by upgrade_transcripts.py. The parent
streams progress, supervises timeouts, and rebuilds reports from output files.
No browser, yt-dlp, or remote media requests occur here.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from pathlib import Path
import sys
import time

# -I removes even the script directory: restore only this trusted repository path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from whisper_worker import transcribe_with_model

EVENT_PREFIX = 'PDE_HQ_EVENT:'


def emit(event: str, **fields) -> None:
    print(EVENT_PREFIX + json.dumps({'event': event, **fields}, ensure_ascii=False), flush=True)


def run_batch(jobs, *, model_name='large-v3', beam_size=5, language='auto',
              compute_type='int8', workers=2, cpu_threads=4, heartbeat=20,
              model_factory=None, transcriber=transcribe_with_model) -> int:
    if workers < 1 or workers > 4 or cpu_threads < 1 or cpu_threads > 32:
        raise ValueError('workers debe ser 1-4 y cpu_threads 1-32')
    if not jobs:
        emit('done', processed=0)
        return 0
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    emit('loading_model', model=model_name, workers=workers, cpu_threads=cpu_threads)
    model = model_factory(model_name, device='cpu', compute_type=compute_type,
                          cpu_threads=cpu_threads, num_workers=workers)
    emit('model_ready', jobs=len(jobs), workers=workers, cpu_threads=cpu_threads)

    def run_one(job):
        media = Path(job['media'])
        folder = Path(job['folder'])
        if not media.is_file():
            raise FileNotFoundError(f'Archivo multimedia no existe: {media}')
        transcriber(media, folder, model, model_name, output_prefix='transcript_hq',
                    beam_size=beam_size, language=language, compute_type=compute_type)
        return job['id']

    failures = 0
    completed = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='whisper-hq') as pool:
        futures = {pool.submit(run_one, job): job for job in jobs}
        pending = set(futures)
        while pending:
            ready, pending = wait(pending, timeout=heartbeat, return_when=FIRST_COMPLETED)
            if not ready:
                emit('heartbeat', completed=completed, total=len(jobs),
                     running=min(len(pending), workers), elapsed_s=round(time.monotonic()-start))
                continue
            for fut in ready:
                job = futures[fut]
                try:
                    fut.result()
                    completed += 1
                    emit('video_ok', id=job['id'], completed=completed, total=len(jobs))
                except Exception as exc:
                    failures += 1
                    emit('video_error', id=job['id'], error=f'{type(exc).__name__}: {exc}'[:1500])
    emit('done', processed=completed, errors=failures, elapsed_s=round(time.monotonic()-start))
    return 1 if failures else 0


def main():
    p = argparse.ArgumentParser(description='Batch Whisper CPU usando un modelo compartido')
    p.add_argument('--jobs-file', type=Path, required=True)
    p.add_argument('--model', default='large-v3')
    p.add_argument('--beam-size', type=int, default=5)
    p.add_argument('--language', default='auto')
    p.add_argument('--compute-type', choices=['int8','float32'], default='int8')
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--cpu-threads', type=int, default=4)
    p.add_argument('--heartbeat', type=int, default=20)
    args = p.parse_args()
    try:
        jobs = json.loads(args.jobs_file.read_text(encoding='utf-8'))
        if not isinstance(jobs, list) or any(not isinstance(x, dict) for x in jobs):
            raise ValueError('El lote debe contener una lista de videos')
        return run_batch(jobs, model_name=args.model, beam_size=args.beam_size,
                         language=args.language, compute_type=args.compute_type,
                         workers=args.workers, cpu_threads=args.cpu_threads,
                         heartbeat=max(1, args.heartbeat))
    except Exception as exc:
        emit('fatal', error=f'{type(exc).__name__}: {exc}'[:1500])
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
