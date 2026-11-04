"""Run faster-whisper on CPU in a separate process.

An incompatible CUDA/cuDNN installation can crash native CTranslate2 code and
terminate Python. This worker isolates that failure from the scraper. No GPU
libraries are required when device='cpu'.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def atomic_write(path: Path, contents: str) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(contents, encoding='utf-8')
    tmp.replace(path)


def transcribe(audio: Path, folder: Path, model_name: str) -> None:
    from faster_whisper import WhisperModel

    folder.mkdir(parents=True, exist_ok=True)
    # Crucial: never device='auto' here. On Windows this can select CUDA even
    # if the required cuDNN 9 DLLs are missing, causing a native process crash.
    threads = min(4, max(1, os.cpu_count() or 1))
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=threads)
    segments, info = model.transcribe(str(audio), beam_size=3, vad_filter=True)
    items = [
        {'text': item.text.strip(), 'start': item.start, 'duration': item.end - item.start}
        for item in segments if item.text.strip()
    ]
    if not items:
        raise RuntimeError('Whisper no detectó segmentos de voz; se conserva el video como pendiente')
    result = {'language': info.language, 'segments': items,
              'method': 'faster-whisper', 'device': 'cpu', 'compute_type': 'int8'}
    atomic_write(folder / 'transcript.json', json.dumps(result, ensure_ascii=False, indent=2))
    atomic_write(folder / 'transcript.txt', '\n'.join(
        f"[{segment['start']:.1f}s] {segment['text']}" for segment in items) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description='Transcribe audio safely using CPU INT8')
    parser.add_argument('audio', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--model', default='small')
    args = parser.parse_args()
    try:
        transcribe(args.audio, args.folder, args.model)
    except Exception as exc:
        print(f'Whisper CPU no pudo transcribir: {type(exc).__name__}: {exc}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
