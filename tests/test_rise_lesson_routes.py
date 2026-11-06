"""Synthetic, credential-free fixtures for Rise HTML5 chapter navigation."""
import json
import tempfile
import unittest
from pathlib import Path

from recover_path_resources import (
    safe_lesson_url, rise_lesson_id, routed_training_urls,
    rise_frame_metadata, capture_current_training_frame, merge_embed_evidence,
)

BASE = ('https://storage.googleapis.com/cloud-training/cls-html5-courses/'
        'T-DLAKES-I/V3.0/T-DLAKES-I/content/index.html')
LESSON = 'tZDIZhk2WifguYf1im0eEGCIBSEREkMc'  # structure-only example, not private
OTHER = 'bHjA5N1mL3S5ACXWZZKqp48hnVI3MX3q'
URL = BASE + '#/lessons/' + LESSON
GOOGLE_PAGE = 'https://www.skills.google/paths/16/course_templates/54/documents/631438'


class FakeLocator:
    def __init__(self, name, frame):
        self.name, self.frame = name, frame

    @property
    def first(self):
        return self

    def get_attribute(self, attr, **kwargs):
        if attr == 'data-lesson-id':
            return self.frame.dom_lesson_id
        if attr == 'src':
            return self.frame.url
        return None

    def inner_text(self, **kwargs):
        if self.name == '.lesson-header__title':
            return 'Course introduction'
        return 'Data lakes and data warehouses are important for managing analytical data.'

    def evaluate_all(self, script):
        return ['sample-block-0001', 'sample-block-0002']

    def screenshot(self, **kwargs):
        return b'fake-png-not-for-production'

    def count(self):
        return 1

    def nth(self, i):
        return self


class FakeFrame:
    def __init__(self, url=URL, dom_lesson_id=LESSON):
        self.url, self.dom_lesson_id = url, dom_lesson_id

    def locator(self, selector):
        return FakeLocator(selector, self)


class FakePage:
    def __init__(self, frame):
        self.frames = [frame]
        self.frame = frame
        self.url = GOOGLE_PAGE

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        return FakeLocator(selector, self.frame)


class RiseRouteTests(unittest.TestCase):
    def test_hash_preserved_and_sensitive_query_removed(self):
        signed = BASE + '?X-Goog-Signature=not-for-output#/lessons/' + LESSON
        self.assertEqual(safe_lesson_url(signed), URL)
        self.assertEqual(rise_lesson_id(signed), LESSON)
        self.assertIsNone(rise_lesson_id(BASE))
        self.assertIsNone(safe_lesson_url(BASE + '#/quizzes/abc'))
        self.assertIsNone(safe_lesson_url('https://evil.example/content/index.html#/lessons/' + LESSON))

    def test_selected_route_recovered_from_original_iframe(self):
        self.assertEqual(routed_training_urls(FakePage(FakeFrame()), [BASE]), [URL])
        self.assertEqual(routed_training_urls(FakePage(FakeFrame()), ['https://evil.example/'] ), [])

    def test_mapping_verified_only_if_dom_matches_url_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'lesson'
            folder.mkdir(parents=True)
            result = capture_current_training_frame(FakePage(FakeFrame()), [BASE], out, folder)
            self.assertTrue(result['lesson_mapping_verified'])
            self.assertEqual(result['lesson_id'], LESSON)
            self.assertEqual(result['visible_block_count'], 2)
            self.assertEqual(result['lesson_route'], URL)
            self.assertEqual(result['status'], 'partial')  # mapping != exhaustive extraction
            saved = json.loads((out / result['lesson_metadata_file']).read_text('utf8'))
            self.assertEqual(saved['lessons'][0]['dom_lesson_id'], LESSON)
            self.assertNotIn('cookie', (out / result['lesson_metadata_file']).read_text('utf8').lower())

    def test_different_dom_id_keeps_partial_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'lesson'
            folder.mkdir(parents=True)
            result = capture_current_training_frame(FakePage(FakeFrame(dom_lesson_id=OTHER)),
                                                    [BASE], out, folder)
            self.assertFalse(result['lesson_mapping_verified'])
            self.assertIsNone(result['lesson_route'])
            self.assertIn('not_verified', result['reason'])

    def test_merge_retains_correct_lesson_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'lesson'
            folder.mkdir(parents=True)
            inline = capture_current_training_frame(FakePage(FakeFrame()), [BASE], out, folder)
            combined = merge_embed_evidence(out, folder, inline,
                           {'status': 'partial', 'visual_files': [], 'embedded_sources': []})
            self.assertTrue(combined['lesson_mapping_verified'])
            self.assertEqual(combined['lesson_route'], URL)
            self.assertEqual(combined['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
