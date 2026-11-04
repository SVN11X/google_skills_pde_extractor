"""Offline regression tests for the Windows cuDNN crash and resume behavior."""
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import extractor
import whisper_worker


class WhisperCpuTests(unittest.TestCase):
    def test_worker_explicitly_uses_cpu_int8_and_writes_transcript(self):
        calls = {}

        class Segment:
            text, start, end = 'Test transcription', 0.0, 1.5

        class Model:
            def __init__(self, model, **kwargs):
                calls.update(kwargs)
                self.name = model

            def transcribe(self, filename, **kwargs):
                return iter([Segment()]), types.SimpleNamespace(language='en')

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            audio = folder / 'source.mp4'
            audio.write_bytes(b'fake audio')
            with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}):
                whisper_worker.transcribe(audio, folder / 'out', 'small')
            self.assertEqual(calls['device'], 'cpu')
            self.assertEqual(calls['compute_type'], 'int8')
            self.assertIn('Test transcription', (folder / 'out' / 'transcript.txt').read_text())
            self.assertEqual(json.loads((folder / 'out' / 'transcript.json').read_text())['device'], 'cpu')

    def test_worker_preserves_existing_transcript_on_error(self):
        class Model:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, *args, **kwargs):
                raise RuntimeError('transcription error')

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder / 'transcript.txt').write_text('already complete', encoding='utf-8')
            with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}):
                with self.assertRaises(RuntimeError):
                    whisper_worker.transcribe(folder / 'audio.mp4', folder, 'small')
            self.assertEqual((folder / 'transcript.txt').read_text(), 'already complete')

    def test_crashing_native_worker_becomes_error_without_killing_scraper(self):
        bad = subprocess.CompletedProcess(['python'], returncode=3221226505,
                                          stdout='', stderr='Missing cudnn_ops64_9.dll')
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            with patch.object(extractor.subprocess, 'run', return_value=bad):
                error = extractor.run_whisper(folder / 'audio.mp4', folder, 'small')
            self.assertIn('3221226505', error)
            self.assertIn('cudnn_ops64_9.dll', error)

    def test_timeout_becomes_recoverable_error(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            with patch.object(extractor.subprocess, 'run', side_effect=subprocess.TimeoutExpired('Whisper', 1800)):
                error = extractor.run_whisper(folder / 'audio.mp4', folder, 'small')
            self.assertIn('1800', error)

    def test_media_is_preserved_if_whisper_fails_for_future_resume(self):
        vid = 'UdtAa7t--n0'
        pages = {'x': {'url': 'https://www.skills.google/x', 'videos': [{'id': vid}]}}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            folder = out / 'videos' / vid
            folder.mkdir(parents=True)
            media = folder / 'source.mp4'
            media.write_bytes(b'video-bytes')
            with patch.object(extractor, 'yt_fetch_transcript', return_value='no captions'):
                with patch.object(extractor, 'run_yt_dlp_subtitles', return_value='no subtitles'):
                    with patch.object(extractor, 'run_whisper', return_value='worker failed'):
                        result = extractor.process_videos(pages, out, frames=False, whisper=True)
            self.assertTrue(media.exists(), 'Audio/video must survive a failed Whisper attempt')
            self.assertEqual(result[0]['transcript'], 'unavailable')

    def test_completed_video_skips_network_and_whisper(self):
        video_id = 'etSDI9eM3QQ'
        pages = {'a': {'url': 'https://www.skills.google/path/a', 'videos': [{'id': video_id}]}}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            folder = out / 'videos' / video_id
            (folder / 'frames').mkdir(parents=True)
            (folder / 'transcript.txt').write_text('already transcribed\n')
            (folder / 'frames' / 'frame_00001.jpg').write_bytes(b'jpg')
            with patch.object(extractor, 'download_video', side_effect=AssertionError('must not download')):
                with patch.object(extractor, 'run_whisper', side_effect=AssertionError('must not transcribe')):
                    results = extractor.process_videos(pages, out, frames=True, whisper=True)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]['reused_from_disk'])
            self.assertEqual(results[0]['frames'], 1)
            self.assertEqual(json.loads((out / 'videos_manifest.json').read_text())[0]['transcript'], 'ok')


if __name__ == '__main__':
    unittest.main()
