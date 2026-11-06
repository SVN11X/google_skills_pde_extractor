from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
import zipfile
import io
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recover_path_resources import (
    safe_asset_url, resource_type, page_resources, write_inventory, download_asset,
    quiz_has_questions, find_download_urls, find_bundle_urls, collect_embed_text,
    read_office_text, decode_binary_type, download_via_visible_button,
    is_training_html_url, training_html_urls, capture_current_training_frame, merge_embed_evidence,
)
from package_security import redact_signed_urls
from package_full_export import package
from build_ai_corpus import build
from audit_complete_path import audit


class ResourceTests(unittest.TestCase):
    def test_scope_and_url_security(self):
        self.assertEqual(resource_type('https://www.skills.google/paths/16/course_templates/53/quizzes/123'), 'quiz')
        self.assertEqual(resource_type('https://www.skills.google/paths/16/course_templates/53/documents/123'), 'document')
        self.assertEqual(resource_type('https://www.skills.google/paths/16/course_templates/53/html_bundles/123'), 'html_bundle')
        self.assertIsNone(resource_type('https://example.com/paths/16/course_templates/53/quizzes/123'))
        self.assertFalse(safe_asset_url('http://storage.googleapis.com/a'))
        self.assertFalse(safe_asset_url('https://storage.googleapis.com.evil.example/a'))
        self.assertTrue(safe_asset_url('https://storage.googleapis.com/course/a.pdf'))

    def test_google_skills_document_can_be_html_course_not_pdf(self):
        html = ('https://storage.googleapis.com/cloud-training/cls-html5-courses/'
                'T-DLAKES-I/V3.0/T-DLAKES-I/content/index.html')
        self.assertTrue(is_training_html_url(html))
        self.assertFalse(is_training_html_url('https://storage.googleapis.com/public.pdf'))
        self.assertFalse(is_training_html_url('https://evil.test/cls-html5-courses/index.html'))
        links = [{'url': html, 'label': 'Download document', 'tag': 'ql-button'},
                 {'url': html, 'label': '', 'tag': 'ql-iframe'}]
        self.assertEqual(training_html_urls(links), [html])
        self.assertTrue(all(is_training_html_url(u) for u in find_download_urls(links)))

    def test_capture_only_trusted_visible_training_frame(self):
        url = ('https://storage.googleapis.com/cloud-training/cls-html5-courses/'
               'T-DLAKES-I/V3.0/T-DLAKES-I/content/index.html')
        class Body:
            def inner_text(self, **kwargs): return 'BigQuery storage lesson: partitioned tables and clustering.'
            def screenshot(self, **kwargs): return b'FAKE PNG DATA'
        class Frame:
            def __init__(self, path): self.url = path
            def locator(self, name):
                if self.url.startswith('https://evil.test'):
                    raise AssertionError('untrusted frame was read')
                return Body()
        class Page:
            frames = [Frame('https://www.skills.google/paths/16'),
                      Frame('https://evil.test/tracker.html'),
                      Frame(url + '#page=3')]
            def wait_for_timeout(self, ms): pass
        with tempfile.TemporaryDirectory() as td:
            out = Path(td); folder = out / 'pages' / 'some_lesson'; folder.mkdir(parents=True)
            item = capture_current_training_frame(Page(), [url], out, folder)
            self.assertEqual(item['status'], 'partial')
            self.assertFalse(item['lesson_mapping_verified'])
            self.assertEqual(item['captured_states'], 1)
            self.assertIn('partitioned tables', (out / item['content_file']).read_text())
            self.assertNotIn('evil.test', json.dumps(item))
            self.assertTrue((out / item['visual_files'][0]).is_file())

    def test_merge_inline_and_detached_text_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); folder = root / 'pages' / 'html_1'; folder.mkdir(parents=True)
            a = folder / 'embedded_lesson_visible.md'
            b = folder / 'embedded_content.md'
            a.write_text('Lesson A - current page', encoding='utf-8')
            b.write_text('Public slide 1', encoding='utf-8')
            joined = merge_embed_evidence(root, folder,
                        {'content_file': a.relative_to(root).as_posix(), 'captured_states': 1,
                         'visual_files': [], 'embedded_sources': ['https://storage.googleapis.com/x']},
                        {'content_file': b.relative_to(root).as_posix(), 'captured_states': 1,
                         'visual_files': [], 'embedded_sources': ['https://storage.googleapis.com/x']})
            self.assertEqual(joined['status'], 'partial')
            self.assertFalse(joined['lesson_mapping_verified'])
            data = (root / joined['content_file']).read_text()
            self.assertIn('current page', data)
            self.assertIn('Public slide', data)

    def test_signed_urls_cannot_leak_to_shareable_text(self):
        raw = 'PDF: https://storage.googleapis.com/x/d.pdf?GoogleAccessId=a&Signature=SECRET&Expires=123) test'
        clean = redact_signed_urls(raw)
        self.assertIn('https://storage.googleapis.com/x/d.pdf)', clean)
        self.assertNotIn('SECRET', clean)
        self.assertNotIn('GoogleAccessId', clean)

    def test_landing_is_not_content(self):
        self.assertFalse(quiz_has_questions('5 questions 80% passing score Start quiz'))
        self.assertTrue(quiz_has_questions('Question 1 of 5. Choose one. A) BigQuery B) Dataflow C) Cloud Storage D) Dataproc'))

    def test_find_actual_document_and_bundle_links(self):
        links = [
            {'url': 'https://storage.googleapis.com/a.pdf?Signature=secret', 'label': 'Download document', 'tag': 'ql-button'},
            {'url': 'https://storage.googleapis.com/course/index.html', 'label': '#html-bundle-iframe', 'tag': 'ql-iframe'},
            {'url': 'https://evil.test/steal', 'label': 'Download document', 'tag': 'a'},
        ]
        self.assertEqual(len(find_download_urls(links)), 2) # PDF first; iframe is metadata fallback
        self.assertEqual(find_bundle_urls(links), ['https://storage.googleapis.com/course/index.html'])

    def test_pdf_download_saves_bytes_and_never_signed_url(self):
        class Resp:
            status = 200
            headers = {'content-type': 'application/pdf', 'content-length': '17'}
            def body(self): return b'%PDF-1.7\nhello\n'
        class Req:
            def get(self, *args, **kwargs): return Resp()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            item = download_asset(SimpleNamespace(request=Req()), 'https://storage.googleapis.com/x.pdf?Signature=SENSITIVE', root,
                                  'https://www.skills.google/paths/16/course_templates/1133/documents/648727')
            self.assertEqual(item['status'], 'recovered')
            self.assertTrue((root / item['file']).exists())
            self.assertNotIn('Signature', json.dumps(item))
            self.assertNotIn('SENSITIVE', json.dumps(item))

    def test_http_429_recorded_without_retry(self):
        class Req:
            calls = 0
            def get(self, *args, **kwargs):
                self.calls += 1
                return SimpleNamespace(status=429)
        req = Req()
        with tempfile.TemporaryDirectory() as td:
            item = download_asset(SimpleNamespace(request=req), 'https://storage.googleapis.com/doc.pdf', Path(td), 'https://www.skills.google/documents/1')
            self.assertEqual(item['status'], 'blocked')
            self.assertEqual(req.calls, 1)

    def test_octet_stream_pdf_is_recognized_by_signature(self):
        class Req:
            def get(self, *args, **kwargs):
                return SimpleNamespace(status=200, headers={'content-type': 'application/octet-stream'},
                                       body=lambda: b'%PDF-1.5\nsynthetic')
        with tempfile.TemporaryDirectory() as td:
            item = download_asset(SimpleNamespace(request=Req()), 'https://storage.googleapis.com/doc', Path(td),
                                  'https://www.skills.google/paths/16/course_templates/53/documents/1')
            self.assertEqual(item['status'], 'recovered')
            self.assertEqual(item['content_type'], 'application/pdf')

    def test_download_button_fallback_uses_visible_explicit_label(self):
        class Download:
            suggested_filename = 'cloud-data.pdf'
            def save_as(self, path): Path(path).write_bytes(b'%PDF-1.7\nLOCAL TEST')
        class DownloadEvent:
            value = Download()
            def __enter__(self): return self
            def __exit__(self, *args): pass
        class Control:
            def is_visible(self): return True
            def is_enabled(self): return True
            def click(self, **kwargs): pass
        class Controls:
            def count(self): return 1
            def nth(self, i): return Control()
        class Page:
            calls = []
            def get_by_role(self, role, name):
                self.calls.append(role)
                return Controls() if role == 'button' else SimpleNamespace(count=lambda: 0)
            def expect_download(self, timeout): return DownloadEvent()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pg = Page()
            item = download_via_visible_button(pg, root,
                'https://www.skills.google/paths/16/course_templates/54/documents/631438')
            self.assertEqual(item['status'], 'recovered')
            self.assertEqual(item['retrieval_method'], 'visible_download_button')
            self.assertEqual((root / item['file']).read_bytes(), b'%PDF-1.7\nLOCAL TEST')
            self.assertNotIn('download_url', item)
            self.assertEqual(pg.calls, ['button'])

    def test_download_button_absent_never_marks_recovered(self):
        class Page:
            def get_by_role(self, role, name): return SimpleNamespace(count=lambda: 0)
        with tempfile.TemporaryDirectory() as td:
            item = download_via_visible_button(Page(), Path(td), 'https://www.skills.google/test')
            self.assertEqual(item['status'], 'partial')
            self.assertIn('no_usable_download', item['reason'])

    def test_ai_pack_locked_original_uses_new_valid_zip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            build(root)
            target = root / 'ai_library' / 'study_pack_path_16.zip'
            previous = target.read_bytes()
            import build_ai_corpus as corpus_module
            actual = corpus_module.os.replace
            def locked_once(source, dest):
                if Path(dest) == target:
                    raise PermissionError('Simulated Windows shared-file lock')
                return actual(source, dest)
            with patch.object(corpus_module.os, 'replace', side_effect=locked_once):
                result = build(root)
            self.assertEqual(target.read_bytes(), previous)
            self.assertIn('_new_', result['ai_pack_path'])
            self.assertEqual(result['ai_pack_status'], 'original_zip_locked_new_copy_created')
            with zipfile.ZipFile(result['ai_pack_path']) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('study_corpus.jsonl', archive.namelist())
            latest = json.loads((root / 'ai_library' / 'latest_pack.json').read_text())
            self.assertEqual(latest['file'], Path(result['ai_pack_path']).name)

    def test_inventory_contains_unresolved_reason_histogram(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            res = page_resources(root)
            doc = next(item for item in res if item['kind'] == 'document')
            report = write_inventory(root, {doc['url']: {'kind': 'document', 'status': 'partial',
                                                         'reason': 'no_download_link'}})
            self.assertEqual(report['unresolved_reasons']['document']['no_download_link'], 1)
            self.assertEqual(report['resource_totals']['quiz']['not_attempted'], 1)
            self.assertEqual(report['document_source_formats']['unknown'], 1)

    def test_ooxml_docx_text_is_extracted_without_office(self):
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / 'test.docx'
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                z.writestr('word/document.xml',
                           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                           '<w:body><w:p><w:r><w:t>BigQuery supports SQL</w:t></w:r></w:p></w:body></w:document>')
            doc.write_bytes(buffer.getvalue())
            self.assertIn('wordprocessingml.document', decode_binary_type('application/octet-stream', buffer.getvalue()))
            self.assertIn('BigQuery supports SQL', read_office_text(doc))

    def test_extracted_iframe_visual_state_stays_partial(self):
        class Frame:
            url = 'https://storage.googleapis.com/cloud-training/course/index.html'
            def locator(self, value):
                return SimpleNamespace(inner_text=lambda timeout=8500: 'This is a visible training lesson about BigQuery and Dataflow pipelines.')
        class Tab:
            frames = [Frame()]
            def goto(self, *args, **kwargs): return SimpleNamespace(status=200)
            def wait_for_timeout(self, x): pass
            def evaluate(self, *args): pass
            def screenshot(self, **kwargs): return b'PNG_TEST_IMAGE'
            def close(self): pass
        class Context:
            def new_page(self): return Tab()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / 'pages' / 'html_bundle_1'
            folder.mkdir(parents=True)
            state = collect_embed_text(SimpleNamespace(context=Context()),
                         ['https://storage.googleapis.com/cloud-training/course/index.html'], root,
                         folder, traverse_slides=False)
            self.assertEqual(state['status'], 'partial')
            self.assertTrue((root / state['content_file']).is_file())
            self.assertEqual(len(state['visual_files']), 1)
            self.assertTrue((root / state['visual_files'][0]).is_file())

    def fixture(self, root):
        pages = root / 'pages'
        examples = [
            ('https://www.skills.google/paths/16/course_templates/1133/quizzes/650779', 'quiz'),
            ('https://www.skills.google/paths/16/course_templates/1133/documents/648727', 'document'),
            ('https://www.skills.google/paths/16/course_templates/52/html_bundles/592746', 'html_bundle'),
            ('https://www.skills.google/focuses/2794?path=16', 'focus'),
        ]
        for i, (url, _) in enumerate(examples):
            folder = pages / f'p{i}'
            folder.mkdir(parents=True)
            (folder / 'metadata.json').write_text(json.dumps({'url': url, 'title': 'Test'}), encoding='utf-8')
            (folder / 'content.md').write_text('Course material', encoding='utf-8')
        (root / 'initial_catalog.json').write_text(json.dumps({'source_url': 'https://www.skills.google/paths/16',
            'activities': [{'title': 'A Tour', 'url': 'https://www.skills.google/focuses/2794?path=16'}]}), encoding='utf-8')

    def test_offline_inventory_and_thirteenth_standalone(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            resources = page_resources(root)
            self.assertEqual(len(resources), 3)
            report = write_inventory(root, {})
            self.assertEqual(report['resource_totals']['quiz']['not_attempted'], 1)
            self.assertEqual(report['document_source_formats']['unknown'], 1)
            self.assertEqual(report['catalog_activities'], 1)
            self.assertEqual(report['activities'][0]['type'], 'standalone_lab')
            self.assertFalse(report['complete'])
            inventory = audit(root)
            self.assertEqual(inventory['catalog']['activities_with_page_evidence'], 1)
            self.assertEqual(inventory['interactive_unresolved_count'], 3)

    def test_partial_iframe_is_not_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            target = next(v for v in page_resources(root) if v['kind'] == 'html_bundle')
            text = target['folder'] / 'embedded_content.md'
            text.write_text('Slide: Dataflow works on Apache Beam.', encoding='utf-8')
            manifest = {target['url']: {'kind': 'html_bundle', 'status': 'partial',
                        'content_file': str(text.relative_to(root))}}
            report = write_inventory(root, manifest)
            self.assertEqual(report['resource_totals']['html_bundle']['partial'], 1)
            self.assertFalse(report['complete'])

    def test_corpus_includes_recovered_resource_without_false_completeness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            target = next(v for v in page_resources(root) if v['kind'] == 'html_bundle')
            f = target['folder'] / 'embedded_content.md'
            f.write_text('Streaming ingestion is often implemented using Pub/Sub.\n' * 5, encoding='utf-8')
            (root / 'resources_manifest.json').write_text(json.dumps({target['url']: {
                'kind': 'html_bundle', 'status': 'partial', 'content_file': str(f.relative_to(root))}}), encoding='utf-8')
            result = build(root)
            self.assertGreater(result['recovered_resource_chunks'], 0)
            corpus = (root / 'ai_library' / 'study_corpus.jsonl').read_text(encoding='utf-8')
            self.assertIn('recovered_html_bundle', corpus)
            self.assertIn('"resource_status": "partial"', corpus)
            zipname = root / 'ai_library' / 'study_pack_path_16.zip'
            self.assertTrue(zipname.is_file())

    def test_package_excludes_sources_and_secrets_but_includes_docs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self.fixture(root)
            (root / 'pages' / 'p1' / 'metadata.json').write_text(json.dumps({'url': 'https://www.skills.google/a',
                'links': [{'url': 'https://storage.googleapis.com/a.pdf?GoogleAccessId=ABCD&Signature=VERYSECRET'}]}), encoding='utf-8')
            video = root / 'videos' / 'fake'
            video.mkdir(parents=True)
            (video / 'source.mp4').write_bytes(b'video data')
            (video / 'transcript_hq.txt').write_text('Hello from HQ', encoding='utf-8')
            (root / 'assets' / 'documents').mkdir(parents=True)
            (root / 'assets' / 'documents' / 'study.pdf').write_bytes(b'%PDF-1.4')
            result = package(root)
            with zipfile.ZipFile(result['zip']) as z:
                self.assertIn('assets/documents/study.pdf', z.namelist())
                self.assertNotIn('videos/fake/source.mp4', z.namelist())
                self.assertIn('videos/fake/transcript_hq.txt', z.namelist())
                text = z.read('pages/p1/metadata.json').decode('utf-8')
                self.assertNotIn('VERYSECRET', text)
                self.assertIn('FULL_ARCHIVE_MANIFEST.json', z.namelist())


if __name__ == '__main__':
    unittest.main()
