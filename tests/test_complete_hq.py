"""Offline tests. No YouTube, no faster-whisper model download."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import complete_hq
from build_ai_corpus import build
from recover_transcripts import save_json

VIDEOS = ['etSDI9eM3QQ', 'PNsLYHr85Mw', 'G4UPZOmM7hk']


def put_hq(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    data = {'model': 'large-v3', 'language': 'en',
            'segments': [{'text': 'Google Cloud data engineering.', 'start': 0.3, 'duration': 2.0}]}
    save_json(folder / 'transcript_hq.json', data)
    (folder / 'transcript_hq.txt').write_text('[0.3s] Google Cloud data engineering.\n', encoding='utf8')


def put_original(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder / 'transcript.json', {'model': 'small', 'language': 'en',
        'segments': [{'text': 'Cloud Storage example', 'start': 1.0, 'duration': 3}]})
    (folder / 'transcript.txt').write_text('Cloud Storage example\n', encoding='utf8')


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'export_pde'
        save_json(self.out / 'videos_manifest.json', [
            {'id': vid, 'url': f'https://www.youtube.com/watch?v={vid}', 'sources': []}
            for vid in VIDEOS])
        for v in VIDEOS:
            put_original(self.out / 'videos' / v)

    def fake_upgrade(self, out, **kwargs):
        self.assertEqual(kwargs['model'], 'large-v3')
        self.assertEqual(kwargs['limit'], 0)
        for vid in VIDEOS:
            folder = out / 'videos' / vid
            if complete_hq.pick_media(folder):
                put_hq(folder)
        return 0

    def test_no_network_default_preserves_original_and_marks_partial(self):
        attempts = []
        ret = complete_hq.complete(self.out, execute_fn=lambda *a, **kw: attempts.append(a),
                                    upgrader=self.fake_upgrade, corpus_builder=lambda out: None)
        self.assertEqual(ret, 3)
        self.assertEqual(attempts, [])
        report = json.loads((self.out / 'hq_completion_report.json').read_text('utf8'))
        self.assertEqual(report['hq_pending'], 3)
        self.assertEqual(report['hq_pending_ids'], VIDEOS)
        for v in VIDEOS:
            self.assertTrue((self.out / 'videos' / v / 'transcript.txt').exists())
            self.assertFalse((self.out / 'videos' / v / 'transcript_hq.txt').exists())

    def test_three_downloads_only_no_existing_hq_overwritten(self):
        original = self.out / 'videos' / VIDEOS[0]
        put_hq(original)
        calls = []
        def mocked_fetch(options, timeout):
            calls.append(options[-1])
            vid = options[-1].split('v=')[-1]
            (self.out / 'videos' / vid / 'source.m4a').write_bytes(b'x' * 2048)
            return SimpleNamespace(ok=True, reason='')
        ret = complete_hq.complete(self.out, fetch_missing=True, execute_fn=mocked_fetch,
                                    sleep_fn=lambda s: None, upgrader=self.fake_upgrade,
                                    corpus_builder=lambda out: None)
        self.assertEqual(ret, 0)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(VIDEOS[0], ' '.join(calls))
        report = json.loads((self.out / 'hq_completion_report.json').read_text('utf8'))
        self.assertEqual(report['hq_complete'], 3)
        self.assertEqual(report['hq_pending'], 0)

    def test_rate_limit_stops_other_download_attempts(self):
        seen = []
        def blocked(options, timeout):
            seen.append(options)
            return SimpleNamespace(ok=False, reason='ERROR: HTTP Error 429 Too Many Requests')
        ret = complete_hq.complete(self.out, fetch_missing=True, execute_fn=blocked,
                                    sleep_fn=lambda s: None, upgrader=self.fake_upgrade,
                                    corpus_builder=lambda out: None)
        self.assertEqual(ret, 3)
        self.assertEqual(len(seen), 1)
        states = [r['status'] for r in json.loads((self.out / 'hq_completion_report.json').read_text('utf8'))['media_recovery']]
        self.assertEqual(states, ['rate_limited', 'skipped_after_rate_limit', 'skipped_after_rate_limit'])

    def test_local_reuse_from_another_path_before_downloading(self):
        remote = self.root / 'export_paths' / 'path_90' / 'videos' / VIDEOS[0]
        remote.mkdir(parents=True)
        (remote / 'source.webm').write_bytes(b'a' * 2048)
        calls = []
        ret = complete_hq.complete(self.out, execute_fn=lambda *a, **kw: calls.append(a),
                                    upgrader=self.fake_upgrade, corpus_builder=lambda out: None)
        self.assertEqual(ret, 3)
        self.assertEqual(calls, [])
        self.assertTrue((self.out / 'videos' / VIDEOS[0] / 'source.webm').exists())
        self.assertTrue((remote / 'source.webm').exists())
        report = json.loads((self.out / 'hq_completion_report.json').read_text('utf8'))
        self.assertEqual(report['hq_complete'], 1)

    def test_source_and_hq_baseline_matches_build_stats(self):
        # A corrupt partial HQ (missing txt) must fall back to original.
        folder1 = self.out / 'videos' / VIDEOS[0]
        put_hq(folder1)
        folder2 = self.out / 'videos' / VIDEOS[1]
        put_hq(folder2)
        (folder2 / 'transcript_hq.txt').unlink()
        stats = build(self.out)
        self.assertEqual(stats['videos_with_transcript'], 3)
        self.assertEqual(stats['hq_videos'], 1)
        self.assertEqual(stats['fallback_original_videos'], 2)
        self.assertEqual(stats['hq_status'], 'partial')
        line_items = [json.loads(x) for x in (self.out / 'ai_library' / 'study_corpus.jsonl').read_text('utf8').splitlines()]
        by_id = {x['video_id']: x for x in line_items if 'video_id' in x}
        self.assertEqual(by_id[VIDEOS[0]]['provenance'], 'whisper_hq')
        self.assertEqual(by_id[VIDEOS[1]]['provenance'], 'original_transcript')

    def test_no_false_hq_on_yt_dlp_ok_without_file(self):
        vid = VIDEOS[0]
        media, error = complete_hq.fetch_audio(vid, self.out / 'videos' / vid,
            execute_fn=lambda options, timeout: SimpleNamespace(ok=True, reason=''))
        self.assertIsNone(media)
        self.assertIn('source.*', error)


class AllCompleteTest(unittest.TestCase):
    def test_fully_hq_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'export_pde'
            save_json(out / 'videos_manifest.json', [{'id': vid} for vid in VIDEOS])
            for vid in VIDEOS:
                put_hq(out / 'videos' / vid)
                put_original(out / 'videos' / vid)
            self.assertEqual(complete_hq.complete(
                out, fetch_missing=True, execute_fn=lambda *args, **kw: self.fail('Unexpected download'),
                upgrader=lambda *args, **kw: 0, corpus_builder=lambda out: None), 0)
            report = json.loads((out / 'hq_completion_report.json').read_text('utf8'))
            self.assertEqual(report['hq_complete'], 3)
            self.assertFalse(report['media_recovery'])


if __name__ == '__main__':
    unittest.main()
