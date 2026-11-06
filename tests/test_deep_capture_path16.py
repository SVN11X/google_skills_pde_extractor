"""Offline tests: never access Google Skills or use real credentials."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import deep_capture_path16 as deep
from build_ai_corpus import build

LESSON = ('https://storage.googleapis.com/cloud-training/cls-html5-courses/'
          'T-DLAKES-I/V3.0/T-DLAKES-I/content/index.html'
          '#/lessons/tZDIZhk2WifguYf1im0eEGCIBSEREkMc')
ID = 'tZDIZhk2WifguYf1im0eEGCIBSEREkMc'


@pytest.mark.parametrize('label', [
    'Start quiz', 'Submit', 'Check answer', 'Next', 'Continue',
    'Reveal correct answer', 'Retry quiz', 'Iniciar evaluación',
    'Comprobar', 'Siguiente', 'Complete lesson',
])
def test_unsafe_controls_cannot_be_clicked(label):
    assert not deep.is_safe_control({'visible': True, 'disabled': False, 'text': label})


@pytest.mark.parametrize('label', [
    'Chapter 1', 'Show more', 'Expand', 'What is BigQuery?', 'Flip card',
])
def test_safe_study_controls_allowed(label):
    assert deep.is_safe_control({'visible': True, 'disabled': False, 'text': label})
    assert not deep.is_safe_control({'visible': True, 'text': label}, quiz_block=True)


def test_image_guard_blocks_url_query_tokens_and_external_hosts():
    assert deep.sanitize_image_url('assets/figure.png', LESSON) == (
        'https://storage.googleapis.com/cloud-training/cls-html5-courses/'
        'T-DLAKES-I/V3.0/T-DLAKES-I/content/assets/figure.png')
    assert deep.sanitize_image_url('https://evil.example/image.png', LESSON) is None
    assert deep.sanitize_image_url('data:image/png;base64,test', LESSON) is None
    assert deep.sanitize_image_url('https://cdn.qwiklabs.com/a.png?token=secret', LESSON) is None
    assert deep.sanitize_image_url('https://storage.googleapis.com/other/file.png', LESSON) is None
    assert deep.sanitize_image_url('javascript:alert(1)', LESSON) is None


def test_only_exact_route_id_is_valid():
    assert deep.valid_lesson_match(ID, ID)
    assert not deep.valid_lesson_match(ID, 'wrong123456789')
    assert not deep.valid_lesson_match(ID, None)
    assert not deep.valid_lesson_match('bad', 'bad')


def test_no_quiz_start_is_ever_called(tmp_path):
    page = Mock()
    page.locator.return_value.first.inner_text.return_value = 'Start quiz to view questions'
    result = deep._safe_quiz_preview(page, tmp_path, tmp_path)
    assert result['status'] == 'partial'
    assert result.get('quiz_started') is False
    assert not list(tmp_path.glob('*.md'))
    page.get_by_text.assert_not_called()


def test_visible_quiz_questions_are_marked_partial(tmp_path):
    page = Mock()
    page.locator.return_value.first.inner_text.return_value = (
        'Question 1 of 10: Choose one option: What is a data warehouse?\n'
        'A. Cloud Storage\nB. BigQuery\nC. Cloud Run\nD. GKE')
    result = deep._safe_quiz_preview(page, tmp_path, tmp_path)
    assert result['status'] == 'partial'
    assert 'question' in (tmp_path / 'quiz_visible_questions.md').read_text().lower()
    page.get_by_text.assert_not_called()


def test_summary_keeps_false_complete():
    result = deep.summarize({
        '/rise': {'kind': 'html_bundle', 'blocks_visited': 5, 'controls_activated': 8,
                  'states_captured': 3, 'images_saved': 2},
        '/quiz': {'kind': 'quiz', 'status': 'partial'},
    })
    assert result['rise_lessons_tried'] == 1
    assert result['controls_activated'] == 8
    assert result['quiz_pages_checked_without_start'] == 1
    assert result['complete'] is False


def test_capture_lesson_records_only_verified_route_and_unique_states(monkeypatch, tmp_path):
    class FakeControl:
        def __init__(self, block, index):
            self.block, self.index = block, index
        def is_visible(self): return True
        def is_enabled(self): return True
        def click(self, timeout):
            if self.index == 0: self.block.text = 'New revealed fact about data lakes.'
            else: raise AssertionError('Unsafe control was clicked')

    class FakeControlList:
        def __init__(self, block): self.block = block
        def nth(self, index): return FakeControl(self.block, index)

    class FakeBlock:
        def __init__(self): self.text = 'Introduction to data lakes.'
        def scroll_into_view_if_needed(self, timeout): pass
        def inner_text(self, timeout): return self.text
        def locator(self, selector): return FakeControlList(self)

    class FakeFrame:
        def __init__(self, block): self.block = block
        def locator(self, selector):
            assert 'data-block-id=' in selector
            return Mock(first=self.block)

    block = FakeBlock()
    frame = FakeFrame(block)
    page = Mock(url='https://www.skills.google/paths/16/course_templates/54/documents/631438')
    page.wait_for_timeout = lambda *args: None
    monkeypatch.setattr(deep, 'rise_frame_metadata', lambda f:
                        {'lesson_id': ID, 'lesson_title': 'Course introduction'})
    monkeypatch.setattr(deep, '_blocks', lambda f: ['block123456'])
    monkeypatch.setattr(deep, '_visible_controls', lambda b: [
        {'index': 0, 'visible': True, 'text': 'Expand'},
        {'index': 1, 'visible': True, 'text': 'Submit'},
    ])
    monkeypatch.setattr(deep, '_visible_images', lambda *a: [])
    monkeypatch.setattr(deep, '_block_is_quiz', lambda b: False)
    monkeypatch.setattr(deep, '_read_dialog', lambda f: '')
    monkeypatch.setattr(deep, '_screenshot', lambda *a: False)
    monkeypatch.setattr(deep, '_save_training_images', lambda *a: {
        'images_saved': 0, 'images_failed': 0, 'images_limit_reached': False})
    folder = tmp_path / 'pages' / 'one'
    folder.mkdir(parents=True)
    result = deep.capture_lesson(frame, page, LESSON, tmp_path, folder)
    assert result['blocks_visited'] == 1
    assert result['controls_activated'] == 1
    assert result['states_captured'] == 1
    assert result['status'] == 'partial'
    assert result['verified_full_coverage'] is False
    content = (folder / 'rise_deep' / 'lesson_content.md').read_text()
    assert 'New revealed fact about data lakes.' in content
    assert 'Submit' not in content
    proof = json.loads((folder / 'rise_deep' / 'lesson_blocks.json').read_text())
    assert proof['blocks'][0]['controls_safe'] == 1


def test_capture_rejects_mismatched_lesson_without_saving(monkeypatch, tmp_path):
    monkeypatch.setattr(deep, 'rise_frame_metadata', lambda f:
                        {'lesson_id': 'different1234567'})
    result = deep.capture_lesson(Mock(), Mock(), LESSON, tmp_path, tmp_path)
    assert result['reason'] == 'rise_lesson_id_mismatch'
    assert not (tmp_path / 'rise_deep').exists()


def test_ai_corpus_ingests_separate_deep_provenance(tmp_path):
    out = tmp_path / 'export_pde'
    p = out / 'pages' / 'example'
    p.mkdir(parents=True)
    url = 'https://www.skills.google/paths/16/course_templates/54/documents/631438'
    (p / 'content.md').write_text('Normal LMS page title and basic introduction.')
    (p / 'metadata.json').write_text(json.dumps({'url': url, 'title': 'Course intro'}))
    evidence = p / 'rise_deep'
    evidence.mkdir()
    (evidence / 'lesson_content.md').write_text('A new concept visible after opening the accordion.')
    (out / 'rise_deep_manifest.json').write_text(json.dumps({url: {
        'kind': 'document', 'status': 'partial',
        'content_file': 'pages/example/rise_deep/lesson_content.md',
        'verified_full_coverage': False,
    }}))
    stats = build(out)
    corpus = [json.loads(line) for line in (out / 'ai_library' / 'study_corpus.jsonl').read_text().splitlines()]
    deep_chunks = [x for x in corpus if x['kind'] == 'rise_deep_observation']
    assert stats['rise_deep_observation_chunks'] > 0
    assert deep_chunks[0]['resource_status'] == 'partial'
    assert deep_chunks[0]['verified_full_coverage'] is False
    assert 'new concept' in deep_chunks[0]['text']
    assert stats['videos_with_transcript'] == 0
