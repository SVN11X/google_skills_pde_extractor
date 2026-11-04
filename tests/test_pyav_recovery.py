"""Offline checks for recovery of pending Whisper transcripts."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from recover_transcripts import recover, valid_transcript, pick_media

class RecoverTests(unittest.TestCase):
    def setup_manifest(self, out: Path, with_media=True):
        vid = 'UdtAa7t--n0'
        folder = out / 'videos' / vid
        folder.mkdir(parents=True)
        if with_media:
            (folder / 'source.mp4').write_bytes(b'video media' * 500)
        (out / 'videos_manifest.json').write_text(json.dumps([{'id': vid, 'url': 'https://www.youtube.com/watch?v='+vid, 'transcript': 'unavailable'}]), encoding='utf-8')
        return folder

    def test_recovers_from_saved_mp4_without_network(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            folder = self.setup_manifest(out)
            def fake_runner(cmd, **kwargs):
                self.assertIn('whisper_worker.py', ' '.join(cmd))
                self.assertEqual(cmd[1], '-I')
                (folder / 'transcript.txt').write_text('[0.0s] Transcription recovered\n', encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0, '', '')
            code = recover(out, runner=fake_runner)
            self.assertEqual(code, 0)
            self.assertTrue(valid_transcript(folder))
            m = json.loads((out / 'videos_manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(m[0]['transcript'], 'ok')
            report = json.loads((out / 'coverage_report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['youtube_transcripts_pending'], 0)
            self.assertEqual(report['completion_status'], 'complete')

    def test_missing_video_is_counted_without_downloading(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self.setup_manifest(out, with_media=False)
            def no_run(*args, **kwargs):
                raise AssertionError('Whisper must not run without media')
            code = recover(out, runner=no_run)
            self.assertEqual(code, 0)
            report = json.loads((out / 'coverage_report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['youtube_transcripts_pending'], 1)
            self.assertEqual(report['completion_status'], 'partial')

    def test_error_is_saved_and_worker_fails_fast(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            self.setup_manifest(out)
            def fail(cmd, **kwargs):
                return subprocess.CompletedProcess(cmd, 1, '', 'ModuleNotFoundError: No module named av')
            code = recover(out, runner=fail)
            self.assertEqual(code, 1)
            self.assertIn('ModuleNotFoundError', (out/'whisper_recovery_diagnostic.txt').read_text(encoding='utf-8'))
            self.assertEqual(json.loads((out/'whisper_recovery_summary.json').read_text())['failed'], 1)

    def test_already_transcribed_not_rerun(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            folder = self.setup_manifest(out)
            (folder/'transcript.txt').write_text('existing transcript\n', encoding='utf-8')
            def no_run(*args, **kwargs):
                raise AssertionError('Completed transcript must be reused')
            code = recover(out, runner=no_run)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads((out/'whisper_recovery_summary.json').read_text())['already_ok'], 1)

    def test_only_audio_video_media_is_selected(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder/'source.mp4').write_bytes(b'A'*4096)
            (folder/'source.mp4.part').write_bytes(b'B'*65536)
            self.assertEqual(pick_media(folder).name, 'source.mp4')

if __name__ == '__main__':
    unittest.main()
