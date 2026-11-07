"""Offline, read-only integrity audit of Path 16 Rise deep extraction.

Generates a separate gap report and CSV without changing extraction evidence,
starting quizzes, visiting Google Skills or changing completion classifications.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _safe_evidence(out: Path, raw_path: str) -> Path | None:
    if not raw_path or Path(raw_path).is_absolute():
        return None
    root = out.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def audit(manifest: dict, out: Path | None = None) -> dict:
    lessons, quizzes = [], []
    for url, item in manifest.items():
        if not isinstance(item, dict):
            continue
        kind = item.get('kind')
        if kind == 'quiz':
            quizzes.append({'url': url, 'reason': item.get('reason', ''),
                            'has_visible_questions': bool(item.get('content_file')),
                            'started': bool(item.get('quiz_started', False))})
            continue
        if kind not in ('document', 'html_bundle'):
            continue
        states = int(item.get('states_captured') or 0)
        shots = int(item.get('screenshots_saved') or 0)
        gaps = max(0, states - shots)
        activated = int(item.get('controls_activated') or 0)
        missing = max(0, int(item.get('blocks_detected') or 0) -
                      int(item.get('blocks_visited') or 0))
        info = {
            'url': url, 'kind': kind, 'lesson_id': item.get('lesson_id', ''),
            'lesson_mapping_verified': bool(item.get('lesson_mapping_verified')),
            'blocks_detected': int(item.get('blocks_detected') or 0),
            'blocks_visited': int(item.get('blocks_visited') or 0),
            'unvisited_blocks': missing,
            'controls_activated': activated, 'states_captured': states,
            'screenshots_saved': shots, 'unpictured_states': gaps,
            'images_saved': int(item.get('images_saved') or 0),
            'zero_interaction_review': activated == 0,
            'suspected_old_screenshot_cap': gaps > 0 and shots == 12,
            'verified_full_coverage': bool(item.get('verified_full_coverage')),
            'limit_reasons': [], 'audit_detail_available': False,
        }
        if out is not None:
            path = _safe_evidence(out, item.get('evidence_file', ''))
            if path:
                detail = _load(path)
                info['audit_detail_available'] = bool(detail)
                info['limit_reasons'] = detail.get('limitations', [])
                info['visible_image_references'] = detail.get('visible_image_references')
                info['images_failed'] = detail.get('images_failed')
                info['images_limit_reached'] = detail.get('images_limit_reached')
                info['controls_safe'] = detail.get('controls_safe')
                info['controls_detected'] = detail.get('controls_detected')
                info['screenshots_skipped_due_to_limit'] = detail.get(
                    'screenshots_skipped_due_to_limit')
                info['screenshots_failed'] = detail.get('screenshots_failed')
        if gaps:
            info['priority'] = 'high_visual_gap'
        elif missing:
            info['priority'] = 'high_blocks_missing'
        elif activated == 0:
            info['priority'] = 'review_static_or_unsupported_controls'
        else:
            info['priority'] = 'review_other_limitations'
        lessons.append(info)
    lessons.sort(key=lambda x: (-x['unpictured_states'],
                                -x['unvisited_blocks'], x['url']))
    summary = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'rise_deep_manifest.json (and optional on-disk lesson_blocks.json)',
        'rise_lessons': len(lessons),
        'lessons_with_verified_route': sum(x['lesson_mapping_verified'] for x in lessons),
        'blocks_detected': sum(x['blocks_detected'] for x in lessons),
        'blocks_visited': sum(x['blocks_visited'] for x in lessons),
        'controls_activated': sum(x['controls_activated'] for x in lessons),
        'states_captured': sum(x['states_captured'] for x in lessons),
        'screenshots_saved': sum(x['screenshots_saved'] for x in lessons),
        'unpictured_states': sum(x['unpictured_states'] for x in lessons),
        'lessons_with_unpictured_states': sum(x['unpictured_states'] > 0 for x in lessons),
        'suspected_old_screenshot_cap_lessons': sum(x['suspected_old_screenshot_cap'] for x in lessons),
        'zero_interaction_lessons_need_review': sum(x['zero_interaction_review'] for x in lessons),
        'quizzes_checked': len(quizzes),
        'quizzes_with_visible_questions': sum(x['has_visible_questions'] for x in quizzes),
        'quiz_attempts_started_by_capture': sum(x['started'] for x in quizzes),
        'full_coverage_proven': False,
        'caveat': ('Las rutas y bloques detectados no prueban exhaustividad. '
                   'Una lección sin controles puede ser estática o tener controles no compatibles. '
                   'Los estados nuevos pueden incluir cambios solo visuales.'),
    }
    return {'summary': summary, 'lessons': lessons, 'quizzes': quizzes}


def write_audit(out: Path) -> dict:
    manifest_path = out / 'rise_deep_manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(f'No existe {manifest_path}')
    report = audit(_load(manifest_path), out)
    (out / 'rise_deep_gap_audit.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    columns = ('url', 'kind', 'lesson_id', 'priority', 'blocks_detected',
               'blocks_visited', 'unvisited_blocks', 'controls_activated',
               'states_captured', 'screenshots_saved', 'unpictured_states',
               'images_saved', 'zero_interaction_review', 'suspected_old_screenshot_cap',
               'verified_full_coverage')
    with (out / 'rise_deep_gap_priority.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(report['lessons'])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description='Auditar Rise (sin conexión ni descargas)')
    parser.add_argument('--out', type=Path, default=Path('export_pde'))
    args = parser.parse_args()
    report = write_audit(args.out.resolve())
    print(json.dumps(report['summary'], indent=2, ensure_ascii=False))
    print('[LISTO] rise_deep_gap_audit.json + rise_deep_gap_priority.csv')


if __name__ == '__main__':
    main()
