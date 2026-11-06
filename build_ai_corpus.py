"""Build source-grounded, timestamped study data from local Google Skills archives.

No AI model, network, credentials or browser access required. The corpus is
machine-readable JSONL + Markdown, suitable for upload or embedding/indexing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def sha(text: str):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def safe_relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return ''


def path_id_for(out: Path) -> str:
    report = read_json(out / 'coverage_report.json', {})
    match = re.search(r'/paths/(\d+)', str(report.get('path', '')))
    if match:
        return match.group(1)
    match = re.search(r'(?:path_|paths_)(\d+)', out.name)
    return match.group(1) if match else 'unknown'


def split_paragraphs(content: str, max_chars=1800):
    """Bound chunk sizes while retaining paragraph boundaries when possible."""
    paragraphs = re.split(r'\n\s*\n', content)
    pieces, current = [], ''
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # Split unusually long paragraphs deterministically, without dropping text.
        while len(paragraph) > max_chars:
            if current:
                pieces.append(current.strip()); current = ''
            cutoff = paragraph.rfind(' ', 1, max_chars)
            if cutoff < max_chars // 2:
                cutoff = max_chars
            pieces.append(paragraph[:cutoff].strip())
            paragraph = paragraph[cutoff:].strip()
        if paragraph and current and len(current) + len(paragraph) + 2 > max_chars:
            pieces.append(current.strip()); current = ''
        if paragraph:
            current = f'{current}\n\n{paragraph}' if current else paragraph
    if current:
        pieces.append(current.strip())
    return pieces


def video_chunks(data: dict, max_chars=1800):
    """Group contiguous subtitle segments. Start/end always come from source."""
    spans = []
    segments = data.get('segments', []) if isinstance(data, dict) else []
    current = []
    length = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get('text', '')).strip()
        if not text:
            continue
        try:
            start = float(segment['start'])
            duration = max(0.0, float(segment.get('duration', 0)))
        except (ValueError, TypeError, KeyError):
            continue
        entry = {'text': text, 'start': start, 'end': start + duration}
        if current and length + len(text) > max_chars:
            spans.append(current)
            current = []
            length = 0
        current.append(entry)
        length += len(text) + 1
    if current:
        spans.append(current)
    return spans


def frames_for(folder: Path, out: Path, max_items=8):
    frames = []
    for img in sorted(folder.rglob('*.jpg')) + sorted(folder.rglob('*.png')):
        if 'frames' in img.parts or 'frame' in img.name.lower() or 'scene' in img.name.lower():
            relative = safe_relative(img, out)
            if relative:
                frames.append(relative)
        if len(frames) >= max_items:
            break
    return frames


def build(out: Path) -> dict:
    out = out.resolve()
    if not (out / 'pages').is_dir() and not (out / 'videos_manifest.json').is_file():
        raise RuntimeError(f'No se encontraron páginas ni videos en {out}')
    path_id = path_id_for(out)
    corpus = []
    page_count = 0
    for meta_path in sorted((out / 'pages').glob('*/metadata.json')):
        meta = read_json(meta_path, {})
        if not isinstance(meta, dict) or not meta.get('url'):
            continue
        source_file = meta_path.parent / 'content.md'
        if not source_file.is_file():
            continue
        raw = source_file.read_text(encoding='utf-8').strip()
        if not raw:
            continue
        page_count += 1
        for index, chunk in enumerate(split_paragraphs(raw), 1):
            corpus.append({'id': sha(f'{path_id}|{meta["url"]}|{index}|{chunk}'),
                           'path_id': path_id, 'kind': 'page',
                           'title': meta.get('title') or meta['url'],
                           'source_url': meta['url'], 'source_file': safe_relative(source_file, out),
                           'chunk_number': index, 'text': chunk,
                           'provenance': 'extracted_page', 'ai_verified': False})

    video_count = 0
    hq_video_count = 0
    fallback_original_count = 0
    fallback_video_ids = []
    videos = read_json(out / 'videos_manifest.json', [])
    for entry in videos if isinstance(videos, list) else []:
        video_id = entry.get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(video_id)):
            continue
        folder = out / 'videos' / video_id
        enhanced = folder / 'transcript_hq.json'
        transcript = read_json(enhanced, {})
        chunks = video_chunks(transcript)
        if (chunks and transcript.get('model') == 'large-v3' and
                (folder / 'transcript_hq.txt').is_file() and
                (folder / 'transcript_hq.txt').stat().st_size > 3):
            source_file = enhanced
        else:
            source_file = folder / 'transcript.json'
            transcript = read_json(source_file, {})
            chunks = video_chunks(transcript)
            if not chunks:
                continue
        video_count += 1
        if source_file == enhanced:
            hq_video_count += 1
        else:
            fallback_original_count += 1
            fallback_video_ids.append(video_id)
        original_url = entry.get('url') or f'https://www.youtube.com/watch?v={video_id}'
        source_pages = entry.get('sources') or []
        frames = frames_for(folder, out)
        for index, span in enumerate(chunks, 1):
            start, end = span[0]['start'], span[-1]['end']
            text = ' '.join(s['text'] for s in span)
            timed_url = original_url + ('&' if '?' in original_url else '?') + f't={int(start)}s'
            corpus.append({'id': sha(f'{path_id}|{video_id}|{index}|{text}'),
                           'path_id': path_id, 'kind': 'video_transcript',
                           'title': f'Video {video_id}', 'video_id': video_id,
                           'source_url': original_url, 'timestamp_url': timed_url,
                           'source_pages': source_pages, 'source_file': safe_relative(source_file, out),
                           'start_seconds': round(start, 2), 'end_seconds': round(end, 2),
                           'language': transcript.get('language'),
                           'model': transcript.get('model'),
                           'provenance': 'whisper_hq' if source_file == enhanced else 'original_transcript',
                           'frame_files_sample': frames, 'chunk_number': index,
                           'text': text, 'ai_verified': False})

    ai = out / 'ai_library'
    ai.mkdir(parents=True, exist_ok=True)
    index_jsonl = ai / 'study_corpus.jsonl'
    index_jsonl.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in corpus),
                           encoding='utf-8')
    md_lines = ['# Google Skills - biblioteca de estudio verificable', '',
                f'Ruta: `{path_id}`',
                'Contenido extraído automáticamente; cotejar cifras, términos y respuestas con la fuente original.',
                'Usa los enlaces y segundos indicados para comprobar cada afirmación.', '']
    for item in corpus:
        md_lines.append(f"## {item['kind']} | {item['title']}")
        md_lines.append(f"Fuente: {item['source_url']}")
        if 'timestamp_url' in item:
            md_lines.append(f"Tiempo: {item['start_seconds']}–{item['end_seconds']} s | {item['timestamp_url']}")
        md_lines.append(f"Identificador: `{item['id']}` | Calidad: {item['provenance']}")
        md_lines.extend(['', item['text'], ''])
    (ai / 'study_corpus.md').write_text('\n'.join(md_lines) + '\n', encoding='utf-8')
    stats = {'path_id': path_id, 'pages_with_text': page_count, 'videos_with_transcript': video_count,
             'videos_in_manifest': len(videos) if isinstance(videos, list) else 0,
             'hq_videos': hq_video_count,
             'fallback_original_videos': fallback_original_count,
             'fallback_original_video_ids': fallback_video_ids,
             'hq_status': 'complete' if hq_video_count == len(videos) and videos else 'partial',
             'chunks': len(corpus), 'hq_video_chunks': sum(c['provenance']=='whisper_hq' for c in corpus),
             'note': 'La calidad de ASR no se valida automáticamente. Conservar referencias al material original.'}
    (ai / 'index.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    (ai / 'INSTRUCCIONES_IA.md').write_text('''# Cómo estudiar con esta biblioteca

Adjunta `study_corpus.md` (o `study_corpus.jsonl`) a una IA que admita archivos.

## Instrucción recomendada

Eres mi tutor para Google Cloud. Responde usando exclusivamente el material adjunto
para las afirmaciones sobre mis cursos. Incluye la URL de la fuente y, para videos,
el minuto/segundo. Si el material no contiene la respuesta, dilo claramente.
Distingue información literal, interpretación y dudas. No inventes citas.
Explícame los conceptos en español, conserva términos técnicos en inglés con
sus definiciones y prepara preguntas de opción múltiple de dificultad de certificación,
explicando cada alternativa y citando el material utilizado.
Antes de usar cualquier dato sensible, solicita confirmación.

Las transcripciones son automáticas y pueden contener errores. Una respuesta de la
IA no certifica que sea correcta ni sustituye la documentación oficial vigente.
''', encoding='utf-8')
    package = ai / f'study_pack_path_{path_id}.zip'
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name in ('study_corpus.jsonl', 'study_corpus.md', 'index.json', 'INSTRUCCIONES_IA.md'):
            z.write(ai / name, name)
    return stats


def combine(root: Path, legacy: Path | None = None) -> dict:
    root = root.resolve()
    paths = sorted(root.glob('path_*/ai_library/study_corpus.jsonl'))
    if legacy and (legacy / 'ai_library' / 'study_corpus.jsonl').is_file():
        paths.insert(0, (legacy / 'ai_library' / 'study_corpus.jsonl').resolve())
    if not paths:
        raise RuntimeError('No hay bibliotecas path_*/ai_library bajo ' + str(root))
    dest = root / 'combined_ai_library'
    dest.mkdir(parents=True, exist_ok=True)
    seen = set()
    n = 0
    with (dest / 'study_corpus.jsonl').open('w', encoding='utf-8') as target:
        for source in paths:
            for line in source.read_text(encoding='utf-8').splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get('id') in seen:
                    continue
                seen.add(obj.get('id'))
                target.write(json.dumps(obj, ensure_ascii=False) + '\n')
                n += 1
    stats = {'paths': len(paths), 'chunks': n, 'source_libraries': [str(x.parent) for x in paths]}
    (dest / 'index.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    return stats


def main():
    parser = argparse.ArgumentParser(description='Convertir exportaciones locales a biblioteca para IA')
    parser.add_argument('--out', type=Path, default=Path('export_pde'))
    parser.add_argument('--combine', type=Path)
    parser.add_argument('--legacy-out', type=Path, help='Opcional: incluir export_pde original en la colección combinada')
    args = parser.parse_args()
    try:
        stats = combine(args.combine, args.legacy_out) if args.combine else build(args.out)
    except RuntimeError as exc:
        parser.error(str(exc))
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
