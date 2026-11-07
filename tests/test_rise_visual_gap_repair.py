"""Local regression tests; no connection to Google Skills or browser sessions."""
import json
from pathlib import Path

import auditar_rise_deep as auditor
import deep_capture_path16 as deep


def _lesson(kind='html_bundle', states=17, screenshots=12, controls=23):
    return {'kind': kind, 'status': 'partial', 'lesson_mapping_verified': True,
            'evidence_file': 'pages/sample/rise_deep/lesson_blocks.json',
            'lesson_id': 'lesson123456abcdef',
            'blocks_detected': 12, 'blocks_visited': 12,
            'controls_activated': controls, 'states_captured': states,
            'screenshots_saved': screenshots, 'images_saved': 3,
            'verified_full_coverage': False}


def test_manifest_audit_highlights_12_screenshot_cap_and_quiz_boundary():
    manifest = {
        'https://www.skills.google/lessons/a': _lesson(),
        'https://www.skills.google/lessons/b': _lesson(states=0, screenshots=0, controls=0),
        'https://www.skills.google/quizzes/a': {
            'kind': 'quiz', 'status': 'partial', 'quiz_started': False,
            'reason': 'quiz_requires_start_or_no_questions_visible'},
    }
    report = auditor.audit(manifest)
    assert report['summary']['rise_lessons'] == 2
    assert report['summary']['unpictured_states'] == 5
    assert report['summary']['suspected_old_screenshot_cap_lessons'] == 1
    assert report['summary']['zero_interaction_lessons_need_review'] == 1
    assert report['summary']['quiz_attempts_started_by_capture'] == 0
    assert report['summary']['full_coverage_proven'] is False
    assert report['lessons'][0]['priority'] == 'high_visual_gap'


def test_audit_rejects_paths_outside_export(tmp_path):
    out = tmp_path / 'export_pde'
    out.mkdir()
    assert auditor._safe_evidence(out, '../secret.json') is None
    assert auditor._safe_evidence(out, '/absolute/elsewhere.json') is None


def test_visual_repair_only_selected_for_missed_screenshots():
    entry = _lesson()
    assert deep.needs_visual_repair(entry)
    assert not deep.needs_visual_repair(_lesson(states=12, screenshots=12))
    assert not deep.needs_visual_repair(_lesson(kind='quiz', states=17, screenshots=12))
    entry['lesson_mapping_verified'] = False
    assert not deep.needs_visual_repair(entry)


def test_staged_evidence_swap_keeps_original_backup_and_fixes_screenshot_urls(tmp_path):
    out = tmp_path / 'export_pde'
    folder = out / 'pages' / 'example'
    original = folder / 'rise_deep'
    original.mkdir(parents=True)
    (original / 'lesson_content.md').write_text('old evidence', encoding='utf-8')
    (original / 'lesson_blocks.json').write_text('{"old": true}', encoding='utf-8')
    staging = folder / '_rise_repair_test'
    staged = staging / 'rise_deep'
    (staged / 'screenshots').mkdir(parents=True)
    (staged / 'lesson_content.md').write_text('better evidence', encoding='utf-8')
    screenshot = 'pages/example/_rise_repair_test/rise_deep/screenshots/new.png'
    (staged / 'screenshots' / 'new.png').write_bytes(b'png')
    (staged / 'lesson_blocks.json').write_text(json.dumps({
        'blocks': [{'block_id': 'block123', 'states': [{'screenshot': screenshot}]}]}),
        encoding='utf-8')
    response = deep.replace_from_staging(out, folder, staging, {
        'content_file': 'pages/example/_rise_repair_test/rise_deep/lesson_content.md',
        'evidence_file': 'pages/example/_rise_repair_test/rise_deep/lesson_blocks.json',
    })
    assert response['content_file'] == 'pages/example/rise_deep/lesson_content.md'
    assert (original / 'lesson_content.md').read_text() == 'better evidence'
    found = json.loads((original / 'lesson_blocks.json').read_text())
    assert found['blocks'][0]['states'][0]['screenshot'] == 'pages/example/rise_deep/screenshots/new.png'
    backup = list((folder / 'rise_deep_prev').glob('*'))
    assert len(backup) == 1
    assert (backup[0] / 'lesson_content.md').read_text() == 'old evidence'


def test_audit_writes_csv_with_utf8_and_json(tmp_path):
    data = {'https://www.skills.google/lessons/a': _lesson()}
    (tmp_path / 'rise_deep_manifest.json').write_text(json.dumps(data), encoding='utf-8')
    report = auditor.write_audit(tmp_path)
    assert report['summary']['unpictured_states'] == 5
    assert (tmp_path / 'rise_deep_gap_audit.json').exists()
    assert 'high_visual_gap' in (tmp_path / 'rise_deep_gap_priority.csv').read_text(encoding='utf-8-sig')
