"""Create a reproducible, sanitized archive of locally extracted learning materials.

Keeps signed download URL secrets out of the shareable ZIP. Excludes large
source audio/video by default; includes saved document binaries, screenshots,
frames, metadata (sanitized) and page/transcript text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from recover_path_resources import sanitized_origin, timestamp
from build_ai_corpus import path_id_for


EXCLUDED_DIRS = {'ai_library', 'complete_archive', '.google_skills_browser', '.venv'}
EXCLUDED_NAMES = {'runtime_status.json', 'execution.log', 'inflight_page.json'}
MEDIA_EXT = {'.mp4', '.m4a', '.mp3', '.webm', '.wav', '.opus', '.mov', '.mkv'}
from package_security import scrub_data as redact_urls



def is_safe_file(rel: Path, include_media: bool):
    if any(p.startswith('.') and p not in ('.', '..') for p in rel.parts):
        return False
    if any(p in EXCLUDED_DIRS for p in rel.parts):
        return False
    if rel.name in EXCLUDED_NAMES or rel.name.endswith(('.tmp', '.part', '.ytdl')):
        return False
    if not include_media and rel.suffix.lower() in MEDIA_EXT:
        return False
    # No browser profiles, auth or cached session data in shared export.
    if any(p in ('credentials', 'tokens', 'sessions') for p in rel.parts):
        return False
    return True


def package(out: Path, *, include_media=False, max_file_mb=400) -> dict:
    out = out.resolve()
    if not (out / 'pages').is_dir():
        raise RuntimeError('Falta export_pde/pages; no se construirá un archivo vacío')
    path_id = path_id_for(out)
    dest_dir = out / 'complete_archive'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f'path_{path_id}_recursos_completos.zip'
    temp = dest.with_suffix('.zip.tmp')
    files = []
    skipped = []
    cap = max_file_mb * 1024 * 1024
    manifest_names = {
        'resources_manifest.json', 'resource_coverage_report.json',
        'coverage_report.json', 'hq_completion_report.json', 'initial_catalog.json',
        'videos_manifest.json', 'images_manifest.json',
    }
    for source in sorted(out.rglob('*')):
        if not source.is_file():
            continue
        rel = source.relative_to(out)
        if not is_safe_file(rel, include_media):
            if rel.suffix.lower() in MEDIA_EXT and not include_media:
                skipped.append({'file': rel.as_posix(), 'reason': 'media_excluded_by_default'})
            continue
        size = source.stat().st_size
        if size > cap:
            skipped.append({'file': rel.as_posix(), 'bytes': size, 'reason': 'max_file_size'})
            continue
        # Only known, meaningful export content. Don't accidentally bundle local caches.
        if rel.parts[0] not in ('pages', 'videos', 'assets') and rel.name not in manifest_names:
            continue
        files.append((source, rel))
    entries = []
    with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for source, rel in files:
            data = source.read_bytes()
            if rel.suffix.lower() in ('.json', '.md', '.txt', '.html', '.csv'):
                try:
                    decoded = data.decode('utf-8-sig')
                    if rel.suffix.lower() == '.json':
                        content = redact_urls(json.loads(decoded))
                        data = json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')
                    else:
                        data = redact_urls(decoded).encode('utf-8')
                except (UnicodeError, ValueError):
                    pass
            digest = hashlib.sha256(data).hexdigest()
            archive.writestr(rel.as_posix(), data)
            entries.append({'file': rel.as_posix(), 'bytes': len(data), 'sha256': digest})
        report = {'generated_at': timestamp(), 'path_id': path_id,
                  'files_included': len(entries), 'files_skipped': len(skipped),
                  'source_media_included': include_media, 'included': entries,
                  'skipped': skipped,
                  'note': 'Local archive contents, not proof of complete learning-path coverage. Downloaded files remain subject to their licenses.'}
        archive.writestr('FULL_ARCHIVE_MANIFEST.json', json.dumps(report, ensure_ascii=False, indent=2))
    temp.replace(dest)
    return {k: report[k] for k in ('path_id', 'files_included', 'files_skipped', 'source_media_included')} | {'zip': str(dest)}


def main():
    ap = argparse.ArgumentParser(description='Empaqueta páginas, PDF, imágenes, fotogramas, subtítulos y evidencias locales')
    ap.add_argument('--out', type=Path, default=Path('export_pde'))
    ap.add_argument('--include-source-media', action='store_true', help='Incluir videos y audios pesados opcionalmente')
    ap.add_argument('--max-file-mb', type=int, default=400)
    args = ap.parse_args()
    print(json.dumps(package(args.out, include_media=args.include_source_media,
                             max_file_mb=args.max_file_mb), ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
