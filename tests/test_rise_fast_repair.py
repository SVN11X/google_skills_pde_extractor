"""Regression tests for fast, bounded Rise screenshot repairs (no real browser)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import deep_capture_path16 as deep


BASE = 'https://www.skills.google/paths/16/course_templates/53/html_bundles/'


def make_entry(out, ident, *, states=17, shots=12, kind='html_bundle'):
    url = BASE + ident
    slug = '__'.join(url.split('www.skills.google/')[1].split('/'))
    folder = out / 'pages' / slug
    path = folder / 'rise_deep' / 'lesson_blocks.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"blocks":[]}', encoding='utf-8')
    return url, {
        'kind': kind, 'source_url': url, 'lesson_mapping_verified': True,
        'evidence_file': path.relative_to(out).as_posix(),
        'blocks_detected': 3, 'blocks_visited': 3,
        'states_captured': states, 'screenshots_saved': shots,
        'images_saved': 0,
    }


def test_fast_manifest_selection_uses_only_existing_lesson_evidence(tmp_path):
    out = tmp_path / 'export_pde'
    entries = dict([make_entry(out, '592749'), make_entry(out, '592752'),
                    make_entry(out, '592748', states=0, shots=0)])
    targets = deep.repair_targets_from_manifest(out, entries)
    assert [item['url'].rsplit('/',1)[-1] for item in targets] == ['592749', '592752']
    assert all(item['folder'].is_dir() and item['source_metadata'] == {} for item in targets)


def test_fast_manifest_skips_invalid_url_and_untrusted_evidence_paths(tmp_path):
    out = tmp_path / 'export_pde'
    url, entry = make_entry(out, '592749')
    bad = dict(entry, evidence_file='../secrets.json')
    wrong_kind = dict(entry, kind='document')
    forged = dict(entry, source_url=BASE+'592755')
    entries = {url: bad, BASE+'592755': forged,
               'https://evil.example/paths/16/course_templates/53/html_bundles/592749': entry,
               'https://www.skills.google:443/paths/16/course_templates/53/html_bundles/592749': entry}
    assert not deep.repair_targets_from_manifest(out, entries)
    assert not deep.repair_targets_from_manifest(out, {url: wrong_kind})
    with pytest.raises(ValueError):
        deep.repair_targets_from_manifest(out, {}, 'https://evil.example/path')


def test_repair_bypasses_metadata_scan_and_handles_no_pending(tmp_path, monkeypatch):
    out = tmp_path / 'export_pde'
    out.mkdir()
    url, entry = make_entry(out, '592749', states=0, shots=0)
    (out / 'rise_deep_manifest.json').write_text(json.dumps({url: entry}), encoding='utf-8')
    monkeypatch.setattr(deep, 'page_resources', lambda out: (_ for _ in ()).throw(
        AssertionError('must not scan page metadata in repair mode')))
    summary = deep.run(out, '.fake', repair_screenshots=True)
    assert summary['rise_lessons_tried'] == 1
    assert (out / 'rise_deep_coverage_report.json').exists()


def test_repair_reaches_browser_without_metadata_scan(tmp_path, monkeypatch):
    out = tmp_path / 'export_pde'
    out.mkdir()
    url, entry = make_entry(out, '592749')
    (out / 'rise_deep_manifest.json').write_text(json.dumps({url: entry}), encoding='utf-8')
    monkeypatch.setattr(deep, 'page_resources', lambda out: (_ for _ in ()).throw(
        AssertionError('must not scan page metadata in repair mode')))
    visited = []

    class FakePage:
        def set_default_timeout(self, value):
            pass
        def goto(self, url, **kwargs):
            visited.append(url)
            return SimpleNamespace(status=403)

    class FakeContext:
        pages = [FakePage()]
        def close(self):
            pass

    class FakeBrowser:
        def launch_persistent_context(self, *args, **kwargs):
            return FakeContext()

    class FakePW:
        chromium = FakeBrowser()
        def __enter__(self): return self
        def __exit__(self, *args): pass

    import playwright.sync_api
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', FakePW)
    result = deep.run(out, '.fake', repair_screenshots=True, delay=0)
    assert visited == [url]
    assert result['new_text_states'] == 17
    assert deep._load_json(out / 'rise_deep_manifest.json')[url]['states_captured'] == 17


def test_pending_without_evidence_reports_error_not_silent_success(tmp_path, monkeypatch):
    out = tmp_path / 'export_pde'
    out.mkdir()
    url, entry = make_entry(out, '592749')
    (out / entry['evidence_file']).unlink()
    (out / 'rise_deep_manifest.json').write_text(json.dumps({url: entry}), encoding='utf-8')
    monkeypatch.setattr(deep, 'page_resources', lambda out: (_ for _ in ()).throw(
        AssertionError('must not scan page metadata in repair mode')))
    with pytest.raises(RuntimeError, match='lesson_blocks.json'):
        deep.run(out, '.fake', repair_screenshots=True)
