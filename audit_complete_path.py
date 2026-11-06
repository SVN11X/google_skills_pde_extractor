"""Offline integrity audit of a Google Skills export; no network or browser.

Reports observed files and unresolved materials without pretending that
successfully saved pages imply every hidden lesson has been inspected.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from build_ai_corpus import path_id_for, read_json
from recover_path_resources import write_inventory, timestamp
from extractor import json_write


def exists_nonempty(out: Path, rel: str | None) -> bool:
    if not rel or not isinstance(rel, str):
        return False
    try:
        p = (out / rel).resolve()
        return p.is_relative_to(out) and p.is_file() and p.stat().st_size > 0
    except (OSError, ValueError):
        return False


def audit(out: Path) -> dict:
    out = out.resolve()
    if not (out / 'pages').is_dir():
        raise RuntimeError('No existe exportación local de páginas')
    resources = read_json(out / 'resources_manifest.json', {})
    if not isinstance(resources, dict):
        resources = {}
    resource_report = write_inventory(out, resources)
    page_counts = Counter()
    bad_pages = []
    urls = set()
    for meta in (out / 'pages').glob('*/metadata.json'):
        d = read_json(meta, {})
        url = d.get('url')
        if not url:
            bad_pages.append(meta.parent.name + ': no_url')
            continue
        urls.add(url)
        host = urlparse(url).hostname or 'unknown'
        page_counts[host] += 1
        if not (meta.parent / 'content.md').is_file():
            bad_pages.append(meta.parent.name + ': missing_content_md')
    state = read_json(out / 'crawl_state.json', {})
    visited = state.get('visited', {}) if isinstance(state, dict) else {}
    if not isinstance(visited, dict):
        visited = {}
    statuses = Counter(x.get('status', 'unknown') for x in visited.values() if isinstance(x, dict))
    img = read_json(out / 'images_manifest.json', [])
    if not isinstance(img, list):
        img = []
    images_ok = sum(exists_nonempty(out, v.get('file')) for v in img if isinstance(v, dict))
    images_missing = [v.get('url', '').split('?')[0] for v in img if isinstance(v, dict)
                      and v.get('status') == 'ok' and not exists_nonempty(out, v.get('file'))]
    videos = read_json(out / 'videos_manifest.json', [])
    if not isinstance(videos, list):
        videos = []
    video_ids = {v.get('id') for v in videos if isinstance(v, dict) and
                 re.fullmatch('[a-zA-Z0-9_-]{11}', str(v.get('id', '')))}
    originals = 0
    enhanced = 0
    missing = []
    frames = 0
    for vid in sorted(video_ids):
        folder = out / 'videos' / vid
        if exists_nonempty(out, str((folder / 'transcript.json').relative_to(out))):
            originals += 1
        hq = read_json(folder / 'transcript_hq.json', {})
        if (hq.get('model') == 'large-v3' and
                exists_nonempty(out, str((folder / 'transcript_hq.txt').relative_to(out)))):
            enhanced += 1
        else:
            missing.append(vid)
        frames += len(list(folder.rglob('*.jpg'))) + len(list(folder.rglob('*.png')))
    doc_files = []
    for f in (out / 'assets' / 'documents').rglob('*') if (out / 'assets' / 'documents').is_dir() else []:
        if f.is_file() and f.suffix.lower() in ('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xlsx', '.xls', '.txt', '.csv'):
            doc_files.append(f.relative_to(out).as_posix())
    catalog = read_json(out / 'initial_catalog.json', {})
    acts = catalog.get('activities', []) if isinstance(catalog, dict) else []
    activities = []
    for a in acts:
        u = a.get('url', '')
        p = urlparse(u)
        # Page-file URL key ignores query; canonical parent for standalone labs.
        full = [x for x in urls if urlparse(x).path == p.path]
        if '/course_templates/' in p.path:
            id_match = re.search(r'/course_templates/(\d+)', p.path)
            course_id = id_match.group(1) if id_match else ''
            if not full:
                full = [x for x in urls if f'/course_templates/{course_id}' in urlparse(x).path]
        activities.append({'title': a.get('title'), 'url': u.split('?')[0],
                           'course_or_focus_page_found': bool(full),
                           'evidence_url': sorted(full)[0].split('?')[0] if full else None})
    unresolved = [x for x in resource_report['resources'] if x['status'] != 'recovered']
    report = {
        'generated_at': timestamp(), 'path_id': path_id_for(out),
        'pages': {'metadata_files': sum(page_counts.values()), 'distinct_urls': len(urls),
                  'by_hostname': dict(page_counts), 'missing_content_files': bad_pages,
                  'visited_state_counts': dict(statuses),
                  'note': 'pages metadata include external cloud.google.com documentation and contextual URL aliases'},
        'catalog': {'declared_activities': len(activities),
                    'activities_with_page_evidence': sum(a['course_or_focus_page_found'] for a in activities),
                    'activities': activities},
        'videos': {'discovered': len(video_ids), 'original_transcript_files': originals,
                   'hq_large_v3_files': enhanced, 'missing_hq_ids': missing,
                   'frame_files': frames},
        'images': {'manifest_count': len(img), 'existing': images_ok,
                   'marked_ok_but_missing': images_missing},
        'documents': {'local_document_files': len(doc_files), 'files': doc_files},
        'interactive_resources': resource_report['resource_totals'],
        'interactive_unresolved_count': len(unresolved),
        'extraction_exhaustiveness': 'not_proven' if unresolved or bad_pages or len(activities) < 1 else 'local_inventory_complete_only',
        'limitations': [
            'Resource landing pages do not prove that quizzes or interactive slide branches were captured.',
            'The local inventory cannot discover content concealed from the saved catalog or account.',
            'Videos HQ files are present but ASR wording is not manually validated.',
            'Packaged text, images and binaries are separate from the public Google Skills website.'
        ],
    }
    json_write(out / 'extraction_integrity_report.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description='Auditoría offline de la extracción completa')
    ap.add_argument('--out', type=Path, default=Path('export_pde'))
    args = ap.parse_args()
    result = audit(args.out)
    print(json.dumps({
        'catalog_activities': result['catalog']['declared_activities'],
        'activities_with_evidence': result['catalog']['activities_with_page_evidence'],
        'pages': result['pages']['metadata_files'],
        'videos_hq': f"{result['videos']['hq_large_v3_files']}/{result['videos']['discovered']}",
        'interactive_pending': result['interactive_unresolved_count'],
        'status': result['extraction_exhaustiveness'],
        'report': str(args.out / 'extraction_integrity_report.json'),
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
