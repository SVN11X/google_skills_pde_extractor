"""Regression: a slow first iframe can be verified in its own trusted Rise tab."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recover_path_resources import merge_embed_evidence, run, sanitized_origin, rise_lesson_id, live_bundle_urls, collect_embed_text

URL = 'https://www.skills.google/paths/16/course_templates/52/html_bundles/592746'
LESSON = 'Lrz7-fyK5nYDZubm2TA2ba-YjsNGcJJN'
BASE = 'https://storage.googleapis.com/cloud-training/cls-html5-courses/T-STREAM-I/3.0/T-STREAM-I/content/index.html'
ROUTE = BASE + '#/lessons/' + LESSON

class DetachedRiseTests(unittest.TestCase):
    def test_real_intro_route_matches_uploaded_outer_html(self):
        self.assertEqual(rise_lesson_id(ROUTE), LESSON)
        self.assertEqual(sanitized_origin(ROUTE), BASE)

    def test_live_iframe_url_keeps_route_without_query_or_recrawl(self):
        class Element:
            def __init__(self, src): self.src = src
            def get_attribute(self, name): return self.src if name == 'src' else None
        class Elements:
            def count(self): return 1
            def nth(self, i): return Element(ROUTE)
        class Page:
            def locator(self, selector): return Elements()
        self.assertEqual(live_bundle_urls(Page()), [ROUTE])

    def test_detached_browser_proves_mapping_from_matching_rise_dom(self):
        class Locator:
            @property
            def first(self): return self
            def wait_for(self, **kw): pass
            def get_attribute(self, attr, **kw): return LESSON
        class Tab:
            main_frame = object()
            def goto(self, *a, **kw):
                class Response: status = 200
                return Response()
            def wait_for_timeout(self, *a): pass
            def locator(self, *a): return Locator()
            def evaluate(self, *a): return None
            def screenshot(self, *a, **kw): return b'PNG sample for a test'
            def close(self): pass
        class Context:
            def new_page(self): return Tab()
        class Page:
            context = Context()
            url = URL + '?private_query_must_not_be_written=secret'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'intro'; folder.mkdir(parents=True)
            with patch('recover_path_resources.rise_frame_metadata', return_value={
                    'lesson_id': LESSON, 'lesson_title': "What's in it for me?",
                    'visible_block_count': 3, 'visible_block_ids': ['block-a', 'block-b', 'block-c']}), \
                 patch('recover_path_resources._visible_training_frame_states', return_value=[
                    (BASE, 'Content of the selected Rise lesson with enough text to store')]):
                result = collect_embed_text(Page(), [ROUTE], out, folder, traverse_slides=False)
            self.assertTrue(result['lesson_mapping_verified'])
            self.assertEqual(result['lesson_route'], ROUTE)
            proof = (out / result['lesson_metadata_file']).read_text('utf-8')
            self.assertIn('detached_lesson_tab', proof)
            self.assertNotIn('private_query_must_not_be_written', proof)

    def test_detached_browser_rejects_mismatched_rise_dom(self):
        class Locator:
            @property
            def first(self): return self
            def wait_for(self, **kw): pass
            def get_attribute(self, attr, **kw): return 'WrongLessonIdentifierABCDE'
        class Tab:
            main_frame = object()
            def goto(self, *a, **kw):
                class Response: status = 200
                return Response()
            def wait_for_timeout(self, *a): pass
            def locator(self, *a): return Locator()
            def close(self): pass
        class Context:
            def new_page(self): return Tab()
        class Page:
            context = Context()
            url = URL
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'intro'; folder.mkdir(parents=True)
            result = collect_embed_text(Page(), [ROUTE], out, folder, traverse_slides=False)
            self.assertFalse(result['lesson_mapping_verified'])
            self.assertIsNone(result['lesson_id'])

    def test_detached_proof_recovers_missing_inline_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'intro'
            folder.mkdir(parents=True)
            inline = {'status': 'partial', 'lesson_mapping_verified': False,
                      'visual_files': [], 'embedded_sources': [], 'content_file': None}
            detached = {'status': 'partial', 'lesson_mapping_verified': True,
                        'lesson_id': LESSON, 'lesson_route': ROUTE,
                        'lesson_title': "What's in it for me?", 'visible_block_count': 4,
                        'lesson_metadata_file': 'pages/intro/rise_detached_lesson_mapping.json',
                        'visual_files': [], 'embedded_sources': [], 'content_file': None}
            result = merge_embed_evidence(out, folder, inline, detached)
            self.assertTrue(result['lesson_mapping_verified'])
            self.assertEqual(result['lesson_mapping_source'], 'detached_verified')
            self.assertEqual(result['lesson_id'], LESSON)
            self.assertEqual(result['visible_block_count'], 4)
            self.assertEqual(result['status'], 'partial')

    def test_inconsistent_inline_and_detached_routes_are_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            folder = out / 'pages' / 'intro'
            folder.mkdir(parents=True)
            inline = {'lesson_mapping_verified': True, 'lesson_id': LESSON,
                      'lesson_route': ROUTE, 'visual_files': [], 'embedded_sources': []}
            detached = {'lesson_mapping_verified': True, 'lesson_id': LESSON,
                        'lesson_route': BASE + '#/lessons/AnotherLessonABCDEFG',
                        'visual_files': [], 'embedded_sources': []}
            result = merge_embed_evidence(out, folder, inline, detached)
            self.assertFalse(result['lesson_mapping_verified'])
            self.assertEqual(result['lesson_mapping_source'], 'conflicting_routes')
            self.assertIn('conflict', result['reason'])

    def test_target_filter_fails_closed_for_unknown_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('recover_path_resources.page_resources', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'no figura'):
                    run(Path(tmp), '.google_skills_browser', only='html_bundle', only_url=URL)

    def test_target_filter_rejects_non_skills_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('recover_path_resources.page_resources', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'HTTPS'):
                    run(Path(tmp), '.google_skills_browser', only_url='https://other.example/592746')

if __name__ == '__main__':
    unittest.main()
