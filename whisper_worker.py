"""Run high-quality Faster-Whisper on CPU in an isolated Python subprocess.

The worker intentionally avoids device='auto' so unavailable CUDA/cuDNN DLLs
cannot crash the parent process. Existing transcripts are never replaced when
--output-prefix is transcript_hq.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(contents, encoding='utf-8')
    tmp.replace(path)


def transcribe(audio: Path, folder: Path, model_name: str, *, output_prefix: str = 'transcript',
               beam_size: int = 5, language: str = 'auto', compute_type: str = 'int8') -> None:
    if output_prefix not in {'transcript', 'transcript_hq'}:
        raise ValueError('El prefijo debe ser transcript o transcript_hq')
    if beam_size < 1 or beam_size > 10:
        raise ValueError('beam_size debe estar entre 1 y 10')
    if compute_type not in {'int8', 'float32'}:
        raise ValueError('compute_type no permitido')
    from faster_whisper import WhisperModel

    folder.mkdir(parents=True, exist_ok=True)
    threads = min(8, max(1, os.cpu_count() or 1))
    model = WhisperModel(model_name, device='cpu', compute_type=compute_type, cpu_threads=threads)
    kwargs = dict(beam_size=beam_size, vad_filter=True, task='transcribe',
                  condition_on_previous_text=False)
    if language != 'auto':
        kwargs['language'] = language
    segments, info = model.transcribe(str(audio), **kwargs)
    items = []
    for segment in segments:
        value = segment.text.strip()
        if not value:
            continue
        items.append({'text': value, 'start': round(float(segment.start), 3),
                      'duration': round(float(segment.end - segment.start), 3),
                      'avg_logprob': round(float(getattr(segment, 'avg_logprob', 0)), 4),
                      'no_speech_prob': round(float(getattr(segment, 'no_speech_prob', 0)), 4)})
    if not items:
        raise RuntimeError('No se detectaron segmentos hablados; los archivos originales no se modificaron')
    result = {'language': info.language, 'language_probability': getattr(info, 'language_probability', None),
              'segments': items, 'method': 'faster-whisper', 'model': model_name,
              'device': 'cpu', 'compute_type': compute_type, 'beam_size': beam_size,
              'source_media': audio.name, 'quality_mode': output_prefix == 'transcript_hq',
              'note': 'Transcripción automática: puede contener errores; cotejar con audio y material del curso.'}
    atomic_write(folder / f'{output_prefix}.json', json.dumps(result, ensure_ascii=False, indent=2))
    atomic_write(folder / f'{output_prefix}.txt', '\n'.join(
        f"[{segment['start']:.1f}s] {segment['text']}" for segment in items) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description='Transcripción Whisper aislada en CPU sin cuDNN')
    parser.add_argument('audio', type=Path)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--model', default='large-v3')
    parser.add_argument('--output-prefix', choices=['transcript', 'transcript_hq'], default='transcript')
    parser.add_argument('--beam-size', type=int, default=5)
    parser.add_argument('--language', default='auto')
    parser.add_argument('--compute-type', choices=['int8', 'float32'], default='int8')
    args = parser.parse_args()
    try:
        transcribe(args.audio, args.folder, args.model, output_prefix=args.output_prefix,
                   beam_size=args.beam_size, language=args.language, compute_type=args.compute_type)
    except Exception as exc:
        print(f'Whisper CPU no pudo transcribir: {type(exc).__name__}: {exc}', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
