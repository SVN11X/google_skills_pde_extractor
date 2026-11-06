"""Resume-only authorized recovery of Google Skills document, HTML bundle and quiz pages.

Does not revisit the full path, alter quiz answers, bypass access restrictions,
or persist browser cookies / signed download URLs. Never silently marks a
landing page as fully extracted content.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from markdownify import markdownify

from extractor import extract_page, json_write, page_key, slug

RESOURCE_KINDS = {'quizzes': 'quiz', 'documents': 'document', 'html_bundles': 'html_bundle'}
SAFE_ASSET_HOSTS = {
    'storage.googleapis.com', 'cdn.qwiklabs.com', 'www.skills.google',
    'cloud.google.com', 'docs.cloud.google.com',
}
SAFE_MIMES = {
    'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    'application/vnd.ms-powerpoint': '.ppt',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.ms-excel': '.xls',
    'text/plain': '.txt', 'text/csv': '.csv',
}
QUIZ_QUESTION = re.compile(r'\b(?:question\s*\d+\b|questions?\s*\d+\s*(?:of|/)|\d+\s*/\s*\d+\s*questions?)', re.I)
START_QUIZ = re.compile(r'\bstart\s+quiz\b', re.I)
DOWNLOAD_LABEL = re.compile(r'download\s+(?:the\s+)?(?:document|file|pdf)|descargar\s+(?:documento|archivo)', re.I)
MAX_SIZE = 80 * 1024 * 1024
# Articulate Rise URLs are single-page apps: index.html alone is NOT a lesson.
# Unlike ordinary crawler URLs, the constrained #/lessons/<id> fragment is content identity.
RISE_LESSON_FRAGMENT = re.compile(r'^/lessons/([A-Za-z0-9_-]{12,100})$')


def rise_lesson_id(url: str) -> str | None:
    """Return only a well-formed Rise lesson ID from the authorized HTML5 host."""
    if not is_training_html_url(url):
        return None
    match = RISE_LESSON_FRAGMENT.fullmatch(urlparse(url).fragment)
    return match.group(1) if match else None


def safe_lesson_url(url: str) -> str | None:
    """Keep the lesson route, remove all query/signature data, reject other fragments."""
    if not rise_lesson_id(url):
        return None
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path,
                       '', '', '/lessons/' + rise_lesson_id(url)))


def routed_training_urls(page, allowed_urls: list[str]) -> list[str]:
    """Get the actual lesson routes from this Google Skills page, not metadata.

    Older extract_page()/norm_url() intentionally stripped URL fragments, so
    persisted metadata knows the shared HTML5 index but NOT its unique lesson.
    Do not change global crawler normalization or discover other lessons here.
    """
    approved = {sanitized_origin(url) for url in allowed_urls if is_training_html_url(url)}
    results = []
    if not approved:
        return []
    try:
        candidates = [getattr(frame, 'url', '') for frame in page.frames]
    except Exception:
        candidates = []
    try:
        elements = page.locator('ql-iframe[src], iframe[src]')
        for i in range(min(elements.count(), 12)):
            candidates.append(elements.nth(i).get_attribute('src') or '')
    except Exception:
        pass
    for candidate in candidates:
        safe = safe_lesson_url(candidate)
        if safe and sanitized_origin(safe) in approved and safe not in results:
            results.append(safe)
    return results


def rise_frame_metadata(frame) -> dict:
    """Inspect only the currently rendered Rise lesson; do not reveal hidden cards."""
    try:
        lesson_id = frame.locator('[data-lesson-id]').first.get_attribute('data-lesson-id', timeout=4500)
    except Exception:
        lesson_id = None
    if lesson_id and not re.fullmatch(r'[A-Za-z0-9_-]{12,100}', lesson_id):
        lesson_id = None
    try:
        title = frame.locator('.lesson-header__title').first.inner_text(timeout=4500).strip()[:240]
    except Exception:
        title = ''
    try:
        # This reads structural IDs only; it does not read invisible responses.
        ids = frame.locator('[data-block-id]').evaluate_all(
            '(nodes) => [...new Set(nodes.filter(n => n.getClientRects().length > 0)'
            '.map(n => n.getAttribute("data-block-id")))]')
        block_ids = [v for v in ids if isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{6,100}', v)]
    except Exception:
        block_ids = []
    return {'lesson_id': lesson_id, 'lesson_title': title, 'visible_block_count': len(block_ids),
            'visible_block_ids': block_ids[:300]}



def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sanitized_origin(url: str) -> str:
    """Safe for reports: no Google Storage signature, tokens or identifiers in query."""
    p = urlparse(url)
    return f'{p.scheme}://{p.netloc}{p.path}' if p.scheme == 'https' else ''


def safe_asset_url(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == 'https' and (p.hostname or '').lower() in SAFE_ASSET_HOSTS


def resource_type(url: str) -> str | None:
    p = urlparse(url)
    if p.hostname != 'www.skills.google':
        return None
    for path_piece, kind in RESOURCE_KINDS.items():
        if re.search(rf'/{path_piece}/\d+(?:/|$)', p.path):
            return kind
    return None


def page_resources(out: Path):
    """List only resources actually present in saved metadata, no broad recrawl."""
    found = {}
    for path in sorted((out / 'pages').glob('*/metadata.json')):
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        url = item.get('url', '')
        kind = resource_type(url)
        if not kind:
            continue
        found[url] = {'url': url, 'kind': kind, 'folder': path.parent,
                      'source_metadata': item}
    return sorted(found.values(), key=lambda x: (x['kind'], x['url']))


def text_from_html(html: str, url: str) -> tuple[str, str]:
    """Sanitize scripts, forms, inputs and account/credential widgets before saving."""
    item = extract_page(html, url)
    return item['markdown'], item['title']


def expected_question_count(meta: dict) -> int | None:
    content = str(meta.get('description', ''))
    folder = meta.get('_folder')
    if folder and (folder / 'content.md').is_file():
        content += ' ' + (folder / 'content.md').read_text(encoding='utf-8', errors='replace')[:5000]
    match = re.search(r'\b(\d{1,3})\s+questions\b', content, re.I)
    return int(match.group(1)) if match else None


def quiz_has_questions(text: str) -> bool:
    """Do not treat quiz landing / 'Start quiz' alone as questions."""
    text = re.sub(r'\s+', ' ', text)
    if not text or len(text) < 30:
        return False
    if START_QUIZ.search(text) and len(text) < 600 and not QUIZ_QUESTION.search(text):
        return False
    return bool(QUIZ_QUESTION.search(text) or
                (re.search(r'\b(?:choose|select)\s+(?:one|two|all|the\s+correct)', text, re.I)
                 and re.search(r'(?:[A-D][.)]|radio|checkbox)', text, re.I)))


def safe_file_name(value: str, fallback: str, extension: str) -> str:
    name = os.path.basename(value.replace('\\', '/'))
    name = re.sub(r'[^a-zA-Z0-9._-]+', '_', name).strip('._')[:110]
    if not name or name in ('.', '..'):
        name = fallback
    if Path(name).suffix.lower() not in SAFE_MIMES.values():
        name += extension
    return name


def find_download_urls(links: list[dict]) -> list[str]:
    """Prefer explicit Download document anchors over incidental media."""
    urls = []
    for link in links:
        url = link.get('url', '')
        if safe_asset_url(url) and DOWNLOAD_LABEL.search(str(link.get('label') or '')):
            urls.append(url)
    for link in links:
        url = link.get('url', '')
        if safe_asset_url(url) and urlparse(url).hostname == 'storage.googleapis.com' and url not in urls:
            urls.append(url)
    return urls


def find_bundle_urls(links: list[dict]) -> list[str]:
    urls = []
    for link in links:
        url = link.get('url', '')
        if safe_asset_url(url) and link.get('tag') in ('ql-iframe', 'iframe') and url not in urls:
            urls.append(url)
    return urls


def is_training_html_url(url: str) -> bool:
    """Some Google Skills *documents* are actually hosted HTML5 course chapters.

    Never interpret their Download document link as a PDF attachment.  Keep the
    source lesson URL in the report; a shared HTML index does not by itself
    establish which chapter was shown.
    """
    parsed = urlparse(url)
    return (safe_asset_url(url) and parsed.hostname == 'storage.googleapis.com'
            and '/cls-html5-courses/' in parsed.path
            and parsed.path.lower().endswith(('.html', '.htm')))


def training_html_urls(links: list[dict]) -> list[str]:
    urls = []
    for link in links:
        url = link.get('url', '')
        if is_training_html_url(url) and url not in urls:
            urls.append(url)
    return urls


def capture_current_training_frame(page, allowed_urls: list[str], out: Path, folder: Path) -> dict:
    """Capture the selected Rise lesson from the original authenticated LMS page.

    A document page can share the same index.html with 23 other pages. The hash
    #/lessons/<id>, plus the matching DOM data-lesson-id, verifies the mapping.
    We preserve visible content, not hidden assessment answers or app state.
    """
    trusted = {sanitized_origin(url) for url in allowed_urls if is_training_html_url(url)}
    if not trusted:
        return {'status': 'partial', 'reason': 'no_trusted_training_html_url'}
    try:
        page.wait_for_timeout(1200)
        frames = list(page.frames)
    except Exception:
        frames = []
    sections, images, sources, verified_lessons = [], [], [], []
    lesson_metadata = []
    for frame in frames:
        source = sanitized_origin(getattr(frame, 'url', ''))
        if source not in trusted:
            continue
        sources.append(source)
        live_route = safe_lesson_url(getattr(frame, 'url', ''))
        structure = rise_frame_metadata(frame) if live_route else {}
        actual_id = structure.get('lesson_id')
        route_id = rise_lesson_id(live_route or '')
        verified = bool(route_id and actual_id == route_id)
        if verified:
            verified_lessons.append(route_id)
        lesson_metadata.append({
            'lesson_route': live_route, 'route_lesson_id': route_id,
            'dom_lesson_id': actual_id, 'lesson_title': structure.get('lesson_title') or '',
            'visible_block_count': structure.get('visible_block_count', 0),
            'visible_block_ids': structure.get('visible_block_ids', []),
            'mapping_verified': verified,
        })
        try:
            # Rise uses main.lesson-main. Prefer it to the outer course chrome.
            # Fallback is useful for other HTML5 players and existing test fakes.
            if actual_id:
                text = frame.locator('main.lesson-main').first.inner_text(timeout=8500).strip()
            else:
                text = frame.locator('body').inner_text(timeout=8500).strip()
        except Exception:
            try:
                text = frame.locator('body').inner_text(timeout=8500).strip()
            except Exception:
                text = ''
        if len(text) >= 20:
            title = structure.get('lesson_title') or f'Marco {len(sections) + 1}'
            sections.append(f'## {title}\n\n{text}')
        try:
            img = frame.locator('body').screenshot(timeout=14000)
            if img and len(img) < 8 * 1024 * 1024:
                target = folder / 'embedded_screenshots' / f'lesson_inline_{len(images) + 1:03d}.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(img)
                images.append(target.relative_to(out).as_posix())
        except Exception:
            pass
    saved_text = None
    if sections:
        target = folder / 'embedded_lesson_visible.md'
        target.write_text('\n\n---\n\n'.join(sections), encoding='utf-8')
        saved_text = target.relative_to(out).as_posix()
    if lesson_metadata:
        audit_file = folder / 'rise_lesson_mapping.json'
        json_write(audit_file, {'source_page': sanitized_origin(getattr(page, 'url', '')),
                                'lessons': lesson_metadata})
    result = {'status': 'partial', 'resource_format': 'embedded_html_course',
              'html_entrypoints': sorted(trusted),
              'content_file': saved_text, 'characters': sum(len(s) for s in sections),
              'visual_files': images, 'captured_states': len(images),
              'embedded_sources': sorted(set(sources)),
              'lesson_mapping_verified': len(verified_lessons) == 1 and len(lesson_metadata) == 1,
              'lesson_id': verified_lessons[0] if len(verified_lessons) == 1 else None,
              'lesson_route': next((m['lesson_route'] for m in lesson_metadata if m['mapping_verified']), None),
              'lesson_title': next((m['lesson_title'] for m in lesson_metadata if m['mapping_verified']), None),
              'visible_block_count': sum(m['visible_block_count'] for m in lesson_metadata),
              'lesson_metadata_file': (audit_file.relative_to(out).as_posix()
                                       if lesson_metadata else None),
              'reason': ('lesson_mapped; full_chapter_coverage_not_proven' if verified_lessons
                         else 'lesson_frame_captured; lesson_mapping_not_verified' if saved_text or images
                         else 'lesson_frame_not_visible'),
              'note': ('The validated #/lessons/<id> identifies a specific Rise lesson, '
                       'but does not prove interactive/hidden sections were fully extracted.')}
    return result


def infer_office_type(data: bytes) -> str | None:
    """Recognize Office OpenXML by internal member names, without unpacking."""
    if not data.startswith(b'PK'):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if 'word/document.xml' in names:
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            if any(n.startswith('ppt/slides/slide') and n.endswith('.xml') for n in names):
                return 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
            if 'xl/workbook.xml' in names:
                return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    except (OSError, ValueError, zipfile.BadZipFile):
        pass
    return None


def decode_binary_type(mime: str, data: bytes) -> str | None:
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    office = infer_office_type(data)
    if office:
        return office
    if mime in ('text/plain', 'text/csv'):
        return mime
    if mime in SAFE_MIMES and mime not in ('application/pdf',):
        return mime
    return None


def download_asset(context, url: str, out: Path, source_url: str, max_bytes=MAX_SIZE) -> dict:
    """Read trusted content via authenticated browser context; never store signed URL."""
    source = sanitized_origin(url)
    if not safe_asset_url(url):
        return {'status': 'restricted', 'reason': 'untrusted_download_host', 'asset_source': source}
    try:
        response = context.request.get(url, timeout=30000, max_redirects=0)
        status = response.status
        if status in (401, 403, 429):
            return {'status': 'blocked', 'http_status': status, 'asset_source': source}
        if status != 200:
            return {'status': 'failed', 'http_status': status, 'asset_source': source}
        ctype = (response.headers.get('content-type') or '').split(';')[0].strip().lower()
        expected = response.headers.get('content-length')
        if expected and expected.isdecimal() and int(expected) > max_bytes:
            return {'status': 'partial', 'reason': 'file_too_large', 'asset_source': source}
        data = response.body()
        if not data or len(data) > max_bytes:
            return {'status': 'partial', 'reason': 'empty_or_oversized', 'asset_source': source}
        detected = decode_binary_type(ctype, data)
        if not detected or detected not in SAFE_MIMES:
            return {'status': 'partial', 'reason': 'unsupported_or_invalid_document',
                    'content_type': ctype[:80], 'asset_source': source}
        ctype = detected
        digest = hashlib.sha256(data).hexdigest()
        disposition = response.headers.get('content-disposition') or ''
        match = re.search(r'filename\s*=\s*"?([^";]+)', disposition, re.I)
        name = safe_file_name(match.group(1) if match else '', digest[:12], SAFE_MIMES[ctype])
        target = out / 'assets' / 'documents' / hashlib.sha256(source_url.encode()).hexdigest()[:14] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + '.tmp')
        temp.write_bytes(data)
        temp.replace(target)
        return {'status': 'recovered', 'file': target.relative_to(out).as_posix(),
                'bytes': len(data), 'sha256': digest, 'content_type': ctype, 'asset_source': source}
    except Exception as exc:
        return {'status': 'failed', 'reason': type(exc).__name__, 'asset_source': source}



def download_via_visible_button(page, out: Path, source_url: str) -> dict:
    """Fallback for document pages whose download is triggered by a button.

    Only activates explicitly labeled download controls on a *document* page.
    Never navigates quiz or exam controls and never stores signed URLs.
    """
    last = {'status': 'partial', 'reason': 'no_usable_download_link_or_button'}
    for role in ('button', 'link'):
        try:
            controls = page.get_by_role(role, name=DOWNLOAD_LABEL)
            count = min(controls.count(), 3)
        except Exception:
            continue
        for i in range(count):
            try:
                control = controls.nth(i)
                if not control.is_visible() or not control.is_enabled():
                    continue
                # Wait only for actual user-visible browser downloads.
                with page.expect_download(timeout=8500) as pending:
                    control.click(timeout=4500)
                download = pending.value
                with tempfile.NamedTemporaryFile(suffix='.download', delete=False) as temporary:
                    tmp_path = Path(temporary.name)
                try:
                    download.save_as(str(tmp_path))
                    if not tmp_path.is_file() or tmp_path.stat().st_size > MAX_SIZE:
                        last = {'status': 'partial', 'reason': 'button_download_oversized_or_missing'}
                        continue
                    data = tmp_path.read_bytes()
                    detected = decode_binary_type('', data)
                    if detected not in SAFE_MIMES:
                        last = {'status': 'partial', 'reason': 'button_download_unsupported_or_invalid'}
                        continue
                    digest = hashlib.sha256(data).hexdigest()
                    name = safe_file_name(download.suggested_filename or '', digest[:12], SAFE_MIMES[detected])
                    dest = out / 'assets' / 'documents' / hashlib.sha256(source_url.encode()).hexdigest()[:14] / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    staged = dest.with_suffix(dest.suffix + '.tmp')
                    staged.write_bytes(data)
                    staged.replace(dest)
                    return {'status': 'recovered', 'file': dest.relative_to(out).as_posix(),
                            'bytes': len(data), 'sha256': digest, 'content_type': detected,
                            'retrieval_method': 'visible_download_button'}
                finally:
                    tmp_path.unlink(missing_ok=True)
            except Exception as exc:
                last = {'status': 'partial', 'reason': 'button_download_unavailable',
                        'error_type': type(exc).__name__}
    return last

def read_pdf_text(path: Path, max_pages=350) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ''
    try:
        reader = PdfReader(str(path), strict=False)
        parts = []
        for number, page in enumerate(reader.pages):
            if number >= max_pages:
                break
            text = (page.extract_text() or '').strip()
            if text:
                parts.append(f'## Page {number + 1}\n\n{text}')
        return '\n\n'.join(parts)
    except Exception:
        return ''


def read_office_text(path: Path) -> str:
    """Best-effort extraction of visible OOXML text with Python stdlib only."""
    texts = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if path.suffix.lower() == '.docx':
                targets = [x for x in names if x == 'word/document.xml']
            elif path.suffix.lower() == '.pptx':
                targets = sorted(x for x in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', x))
            elif path.suffix.lower() == '.xlsx':
                targets = [x for x in names if x in ('xl/sharedStrings.xml', 'xl/workbook.xml')]
            else:
                return ''
            for name in targets[:300]:
                member = z.getinfo(name)
                if member.file_size > 10 * 1024 * 1024:
                    continue
                tree = ET.fromstring(z.read(name))
                chunks = []
                for node in tree.iter():
                    if node.tag.rsplit('}', 1)[-1] in ('t', 'v') and node.text:
                        chunks.append(node.text.strip())
                if chunks:
                    texts.append(f'## {name}\n\n' + '\n'.join(chunks))
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return ''
    return '\n\n'.join(texts)


def save_document_text(out: Path, item: dict) -> None:
    rel = item.get('file')
    if not rel:
        return
    path = out / rel
    text = ''
    if path.suffix.lower() == '.pdf':
        text = read_pdf_text(path)
    elif path.suffix.lower() in ('.docx', '.pptx', '.xlsx'):
        text = read_office_text(path)
    elif path.suffix.lower() in ('.txt', '.csv'):
        text = path.read_text(encoding='utf-8-sig', errors='replace')
    if text.strip():
        textfile = path.parent / (path.stem + '.md')
        textfile.write_text(text, encoding='utf-8')
        item['text_file'] = textfile.relative_to(out).as_posix()
        item['text_characters'] = len(text)
    else:
        item['text_status'] = 'no_extractable_text_or_optional_parser_missing'


def _visible_training_frame_states(tab, source_url: str) -> list[tuple[str, str]]:
    """Read *visible* rendered text, including accessible nested frames.

    Avoid outerHTML for this material: hidden DOM elements can include quiz
    answers or data the learner has not actually been shown.
    """
    visible = []
    for frame in tab.frames:
        if not safe_asset_url(frame.url):
            continue
        try:
            text = frame.locator('body').inner_text(timeout=8500).strip()
            if len(text) > 50:
                visible.append((sanitized_origin(frame.url), text))
        except Exception:
            continue
    return visible


def _advance_public_slide(tab) -> bool:
    """Navigate an isolated public training tab only; never start/submit a quiz."""
    for frame in tab.frames:
        if not safe_asset_url(frame.url):
            continue
        for kind in ('button', 'link'):
            try:
                candidate = frame.get_by_role(kind, name=re.compile(r'^(next|next slide|continue|siguiente)$', re.I)).first
                if candidate.count() and candidate.is_visible() and candidate.is_enabled():
                    candidate.click(timeout=3000)
                    return True
            except Exception:
                continue
    return False


def collect_embed_text(page, allowed_urls: list[str], out: Path, folder: Path, traverse_slides=True,
                       max_slides=60) -> dict:
    """Capture visible iframe states and screenshots in an isolated training tab.

    No quiz submissions or graded interactions. Clicking an explicit Next slide
    button is only attempted in the detached tab, not on the learner page.
    """
    fragments, sources, visual_files = [], [], []
    seen = set()
    navigation_limit = False
    for url in allowed_urls[:5]:
        if not safe_asset_url(url):
            continue
        tab = page.context.new_page()
        try:
            response = tab.goto(url, wait_until='domcontentloaded', timeout=45000)
            if response and response.status in (401, 403, 429):
                return {'status': 'blocked', 'http_status': response.status,
                        'reason': 'embedded_page_access_restricted'}
            tab.wait_for_timeout(1800)
            expected_id = rise_lesson_id(url)
            if expected_id:
                # The player is a SPA: verify that the requested #/lessons/id
                # finished rendering before merging the detached evidence.
                try:
                    tab.locator('[data-lesson-id]').first.wait_for(state='attached', timeout=12000)
                    actual_id = tab.locator('[data-lesson-id]').first.get_attribute(
                        'data-lesson-id', timeout=5000)
                except Exception:
                    actual_id = None
                if actual_id != expected_id:
                    sources.append(sanitized_origin(url) + ' [lesson_route_not_confirmed]')
                    continue
            # Rise 'Next' can change to ANOTHER lesson: never mix their text.
            for slide in range(max_slides if traverse_slides and not rise_lesson_id(url) else 1):
                try: tab.evaluate('(y)=>window.scrollTo(0,y)', 1800)
                except Exception: pass
                tab.wait_for_timeout(250)
                texts = _visible_training_frame_states(tab, url)
                unique_text = '\n\n'.join(f'Fuente: {origin}\n\n{txt}' for origin, txt in texts)
                screenshot = b''
                try:
                    screenshot = tab.screenshot(full_page=False, timeout=12000)
                except Exception:
                    pass
                signature = hashlib.sha256(unique_text.encode() + screenshot).hexdigest()
                if signature in seen:
                    break
                seen.add(signature)
                if len(unique_text.strip()) > 60:
                    fragments.append(f'## Estado visible {len(fragments) + 1}\n\n{unique_text}')
                    sources.extend(origin for origin, _ in texts)
                if screenshot and len(screenshot) < 8 * 1024 * 1024:
                    relative = folder / 'embedded_screenshots' / f'state_{len(seen):03d}.png'
                    relative.parent.mkdir(parents=True, exist_ok=True)
                    relative.write_bytes(screenshot)
                    visual_files.append(relative.relative_to(out).as_posix())
                if not traverse_slides or not _advance_public_slide(tab):
                    break
                if slide == max_slides - 1:
                    navigation_limit = True
                tab.wait_for_timeout(550)
        except Exception as exc:
            sources.append(sanitized_origin(url) + ' [error:' + type(exc).__name__ + ']')
        finally:
            tab.close()
    if not fragments and not visual_files:
        return {'status': 'partial', 'reason': 'iframe_empty_or_unreachable', 'embedded_sources': sources}
    if fragments:
        content = '\n\n---\n\n'.join(fragments)
        filename = folder / 'embedded_content.md'
        filename.write_text(content, encoding='utf-8')
    else:
        content, filename = '', None
    return {'status': 'partial',
            'content_file': filename.relative_to(out).as_posix() if filename else None,
            'characters': len(content), 'embedded_sources': sorted(set(sources)),
            'visual_files': visual_files, 'captured_states': len(seen),
            'navigation_limit': navigation_limit,
            'reason': 'iframe_visible_states_captured; completeness_not_proven',
            'note': 'Visual states and accessible text captured; graded navigation not automated.'}


def merge_embed_evidence(out: Path, folder: Path, inline: dict, detached: dict) -> dict:
    """Index both the currently selected lesson and any isolated public slides.

    Never substitute the standalone index for a lesson-specific frame without
    recording this uncertainty.  Partial remains partial even with many images.
    """
    fragments, seen = [], set()
    for state in (inline, detached):
        rel = state.get('content_file')
        if not rel:
            continue
        path = out / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace').strip()
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        if text and fingerprint not in seen:
            seen.add(fingerprint)
            fragments.append(text)
    content_file = None
    if fragments:
        dest = folder / 'embedded_content_combined.md'
        dest.write_text('\n\n---\n\n'.join(fragments), encoding='utf-8')
        content_file = dest.relative_to(out).as_posix()
    visuals = list(dict.fromkeys(inline.get('visual_files', []) + detached.get('visual_files', [])))
    return {
        'status': 'partial', 'resource_format': 'embedded_html_course',
        'content_file': content_file, 'characters': sum(len(f) for f in fragments),
        'visual_files': visuals, 'captured_states': len(visuals),
        'inline_states': inline.get('captured_states', 0),
        'isolated_states': detached.get('captured_states', 0),
        'embedded_sources': sorted(set(inline.get('embedded_sources', []) +
                                       detached.get('embedded_sources', []))),
        'lesson_mapping_verified': bool(inline.get('lesson_mapping_verified', False)),
        'lesson_id': inline.get('lesson_id'),
        'lesson_route': inline.get('lesson_route'),
        'lesson_title': inline.get('lesson_title'),
        'visible_block_count': inline.get('visible_block_count', 0),
        'lesson_metadata_file': inline.get('lesson_metadata_file'),
        'reason': ('lesson_mapped; full_chapter_coverage_not_proven'
                   if inline.get('lesson_mapping_verified') else
                   'visible_html_states_captured; lesson_mapping_not_verified'
                   if content_file or visuals else 'html_course_content_not_visible'),
        'note': ('Original lesson is identified only when #/lessons/<id> matches '
                 'data-lesson-id in the rendered Rise document. '
                 'A verified mapping is not proof of complete interactive content.'),
    }


def collect_quiz_state(page, out: Path, folder: Path, opt_in_start=False) -> dict:
    """Reading questions is allowed, but starting attempts requires explicit opt-in."""
    main = page.locator('main').first
    try:
        rendered = main.inner_text(timeout=8000)
    except Exception:
        rendered = ''
    if not quiz_has_questions(rendered) and opt_in_start:
        # May consume quiz attempts; never answer or submit anything.
        start = page.get_by_text(re.compile('^Start quiz$', re.I)).first
        try:
            if start.count() > 0:
                start.click(timeout=8000)
                page.wait_for_timeout(1300)
                rendered = main.inner_text(timeout=8000)
        except Exception as exc:
            return {'status': 'partial', 'reason': 'quiz_start_unavailable',
                    'detail': type(exc).__name__}
    if not quiz_has_questions(rendered):
        return {'status': 'partial', 'reason': 'quiz_landing_or_questions_not_visible',
                'requires_explicit_start': not opt_in_start}
    html = page.locator('html').evaluate('(el)=>el.outerHTML', timeout=12000)
    markdown, _ = text_from_html(html, page.url)
    if not quiz_has_questions(markdown):
        # Keep visible question text only from main, avoid account info in header.
        markdown = rendered
    target = folder / 'quiz_visible_questions.md'
    target.write_text(markdown, encoding='utf-8')
    return {'status': 'partial', 'content_file': target.relative_to(out).as_posix(),
            'characters': len(markdown), 'reason': 'visible_questions_only; unvisited quiz screens not claimed complete',
            'note': 'No answers selected and no quiz submitted.'}


def record_status(record: dict, out: Path, folder: Path) -> bool:
    if record.get('status') != 'recovered':
        return False
    path = record.get('content_file') or record.get('file')
    if not path:
        return False
    candidate = (out / path).resolve()
    return candidate.is_relative_to(out.resolve()) and candidate.is_file() and candidate.stat().st_size > 0


def write_inventory(out: Path, entries: dict) -> dict:
    targets = page_resources(out)
    counter = Counter()
    per_kind = {}
    audit = []
    for target in targets:
        url, kind = target['url'], target['kind']
        rec = entries.get(url) or {'status': 'not_attempted', 'reason': 'not_yet_recovered'}
        status = rec.get('status', 'not_attempted')
        if status == 'recovered' and not record_status(rec, out, target['folder']):
            status = 'partial'
            rec = {**rec, 'status': status, 'reason': 'missing_saved_artifact'}
        # 'partial' never becomes complete simply because content_file exists.
        counter[(kind, status)] += 1
        data = {'url': url, 'kind': kind, 'status': status,
                'file': rec.get('file') or rec.get('content_file'),
                'bytes': rec.get('bytes'), 'sha256': rec.get('sha256'),
                'reason': rec.get('reason'),
                'text_file': rec.get('text_file'),
                'resource_format': rec.get('resource_format'),
                'lesson_mapping_verified': rec.get('lesson_mapping_verified'),
                'visual_files': rec.get('visual_files', []),
                'captured_states': rec.get('captured_states'),
                'lesson_mapping_verified': rec.get('lesson_mapping_verified'),
                'lesson_id': rec.get('lesson_id'),
                'lesson_route': rec.get('lesson_route'),
                'lesson_title': rec.get('lesson_title'),
                'visible_block_count': rec.get('visible_block_count'),
                'lesson_metadata_file': rec.get('lesson_metadata_file')}
        audit.append(data)
        per_kind.setdefault(kind, {'total': 0, 'recovered': 0, 'partial': 0,
                                   'blocked': 0, 'failed': 0, 'not_attempted': 0, 'restricted': 0})
        per_kind[kind]['total'] += 1
        per_kind[kind][status] = per_kind[kind].get(status, 0) + 1
    seed = {}
    try:
        seed = json.loads((out / 'initial_catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    activities = []
    for item in seed.get('activities', []) if isinstance(seed, dict) else []:
        activity_url = item.get('url', '')
        # The 13th activity is a standalone /focuses/ lab, not another course.
        key = re.search(r'/course_templates/(\d+)', activity_url)
        focus = re.search(r'/focuses/(\d+)', activity_url)
        related = [r for r in audit if (key and f'/course_templates/{key.group(1)}/' in r['url'])]
        activities.append({'title': item.get('title'), 'url': sanitized_origin(activity_url),
                           'type': 'course' if key else 'standalone_lab' if focus else 'other',
                           'resources_detected': len(related)})
    reasons = {}
    evidence = {}
    for kind in ('document', 'html_bundle', 'quiz'):
        reasons[kind] = dict(sorted(Counter(
            (r.get('reason') or 'unspecified') for r in audit
            if r['kind'] == kind and r['status'] != 'recovered'
        ).items()))
        typed = [r for r in audit if r['kind'] == kind]
        evidence[kind] = {
            'with_saved_text': sum(any(bool(rel and (out / rel).is_file() and
                                             (out / rel).suffix.lower() == '.md')
                                       for rel in (r.get('file'), r.get('text_file'))) for r in typed),
            'with_saved_image': sum(any((out / v).is_file() for v in r.get('visual_files', [])) for r in typed),
            'with_verified_lesson_mapping': sum(r.get('lesson_mapping_verified') is True for r in typed),
            'with_visible_block_inventory': sum(isinstance(r.get('visible_block_count'), int) and
                                                r['visible_block_count'] > 0 for r in typed),
            'partial_with_evidence': sum(r['status'] == 'partial' and
                                         (bool(r.get('file') and (out / r['file']).is_file()) or
                                          any((out / v).is_file() for v in r.get('visual_files', [])))
                                         for r in typed),
        }
    document_source_types = Counter()
    for target in targets:
        if target['kind'] != 'document':
            continue
        original_links = target.get('source_metadata', {}).get('links', [])
        candidates = find_download_urls(original_links)
        html_links = training_html_urls(original_links)
        binary_links = [url for url in candidates if not is_training_html_url(url)]
        if html_links and not binary_links:
            document_source_types['embedded_html_course'] += 1
        elif binary_links:
            document_source_types['downloadable_file'] += 1
        else:
            document_source_types['unknown'] += 1
    report = {'generated_at': timestamp(), 'path': seed.get('source_url') or '',
              'catalog_activities': len(activities), 'activities': activities,
              'resource_totals': per_kind, 'unresolved_reasons': reasons,
              'evidence_coverage': evidence,
              'document_source_formats': dict(document_source_types),
              'resources': audit,
              'complete': all(v['recovered'] == v['total'] for v in per_kind.values()) and len(activities) > 0,
              'limitations': [
                  'Status recovered means a file or current iframe state exists, not that all interactive screens were traversed.',
                  'Quiz submissions/answers and restricted pages are never bypassed or automated.',
                  'Previously saved videos, images and other media require their own integrity audit.'
              ]}
    json_write(out / 'resource_coverage_report.json', report)
    return report


def run(out: Path, profile_dir: str, *, headless=False, include_quiz_start=False,
        delay=2.0, limit=0, audit_only=False, traverse_slides=True, retry_partial=False, only=None) -> dict:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    saved = out / 'resources_manifest.json'
    try:
        manifest = json.loads(saved.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    targets = page_resources(out)
    if only:
        targets = [target for target in targets if target['kind'] == only]
    if audit_only:
        return write_inventory(out, manifest)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('Playwright no está instalado en este Python') from exc
    attempted = 0
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile_dir, headless=headless,
                    viewport={'width': 1365, 'height': 900}, locale='en-US', accept_downloads=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(12000)
        try:
            for i, target in enumerate(targets, 1):
                url, kind, folder, meta = (target[k] for k in ('url', 'kind', 'folder', 'source_metadata'))
                previous = manifest.get(url, {})
                partial_path = previous.get('content_file')
                partial_exists = bool(partial_path and
                                      (out / partial_path).resolve().is_relative_to(out) and
                                      (out / partial_path).is_file())
                reuse_partial = (previous.get('status') == 'partial' and
                                 partial_exists and not retry_partial)
                visuals_only = (not retry_partial and kind == 'html_bundle' and
                                previous.get('status') == 'partial' and
                                any((out / v).is_file() for v in previous.get('visual_files', [])))
                if record_status(previous, out, folder) or reuse_partial or visuals_only:
                    print(f'[{i}/{len(targets)}] REUTILIZADO {kind}: {sanitized_origin(url)}', flush=True)
                    continue
                if limit and attempted >= limit:
                    break
                attempted += 1
                print(f'[{i}/{len(targets)}] RECUPERANDO {kind}: {sanitized_origin(url)}', flush=True)
                entry = {'kind': kind, 'status': 'partial', 'checked_at': timestamp(),
                         'source_url': sanitized_origin(url)}
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=50000)
                    status = response.status if response else 0
                    if status in (401, 403, 429):
                        entry.update(status='blocked', reason=f'HTTP {status}', http_status=status)
                    elif status >= 400:
                        entry.update(status='failed', reason=f'HTTP {status}', http_status=status)
                    elif urlparse(page.url).hostname not in ('www.skills.google',):
                        entry.update(status='blocked', reason='redirected_away_from_skills_or_login')
                    else:
                        page.wait_for_timeout(600)
                        if kind == 'quiz':
                            entry.update(collect_quiz_state(page, out, folder, include_quiz_start))
                        elif kind == 'html_bundle':
                            links = meta.get('links', [])
                            # Refresh dynamic URLs to capture the newest embed configuration.
                            html = page.locator('html').evaluate('(e)=>e.outerHTML', timeout=12000)
                            recent = extract_page(html, url)
                            links = recent.get('links', []) + links
                            iframe_urls = find_bundle_urls(links)
                            current = capture_current_training_frame(page, iframe_urls, out, folder)
                            # Metadata normalized away the Rise #/lessons/<id> hash.
                            # Recover the selected route from the LIVE iframe; the
                            # bare shared index opens the wrong lesson in a new tab.
                            routed = routed_training_urls(page, iframe_urls)
                            if routed:
                                isolated = collect_embed_text(page, routed, out, folder,
                                                              traverse_slides=False)
                            elif any(is_training_html_url(v) for v in iframe_urls):
                                isolated = {'status': 'partial', 'reason': 'missing_live_lesson_route',
                                            'visual_files': [], 'embedded_sources': []}
                            else:
                                isolated = collect_embed_text(page, iframe_urls, out, folder,
                                                              traverse_slides=traverse_slides)
                            entry.update(merge_embed_evidence(out, folder, current, isolated))
                            entry['routed_lesson_candidates'] = len(routed)
                            if entry.get('lesson_id'):
                                print(f"  Rise: leccion={entry['lesson_id']} bloques={entry.get('visible_block_count', 0)} verificada={entry.get('lesson_mapping_verified')}", flush=True)
                        elif kind == 'document':
                            html = page.locator('html').evaluate('(e)=>e.outerHTML', timeout=12000)
                            recent = extract_page(html, url)
                            links = recent.get('links', []) + meta.get('links', [])
                            urls = find_download_urls(links)
                            html_urls = training_html_urls(links)
                            binary_urls = [candidate for candidate in urls if not is_training_html_url(candidate)]
                            if html_urls and not binary_urls:
                                # Template 54 consists of 24 'document' pages using
                                # a *single shared HTML5 index*, not 24 PDF files.
                                # Reading the iframe inside this page keeps the
                                # LMS lesson selection and avoids a false PDF error.
                                entry.update(capture_current_training_frame(page, html_urls, out, folder))
                                entry['candidate_downloads_tested'] = 0
                                entry['html_document_entrypoints'] = len(html_urls)
                                if entry.get('lesson_id'):
                                    print(f"  Rise: leccion={entry['lesson_id']} bloques={entry.get('visible_block_count', 0)} verificada={entry.get('lesson_mapping_verified')}", flush=True)
                            else:
                                attempts = []
                                downloaded = None
                                for asset_url in binary_urls[:5]:
                                    attempt = download_asset(context, asset_url, out, url)
                                    attempts.append(attempt.get('reason') or
                                                    f"HTTP {attempt.get('http_status')}" if attempt.get('http_status') else
                                                    attempt.get('reason') or attempt['status'])
                                    if attempt['status'] == 'recovered':
                                        downloaded = attempt
                                        break
                                    if attempt.get('http_status') == 429:
                                        downloaded = attempt
                                        break
                                if downloaded is None:
                                    downloaded = download_via_visible_button(page, out, url)
                                entry.update(downloaded)
                                entry['candidate_downloads_tested'] = len(attempts)
                                if entry['status'] != 'recovered' and attempts:
                                    entry['download_attempt_reasons'] = attempts
                                if entry['status'] == 'recovered':
                                    save_document_text(out, entry)
                    # Page is not marked complete for the old crawler; only this manifest changes.
                except Exception as exc:
                    entry.update(status='failed', reason=type(exc).__name__, detail=str(exc)[:180])
                manifest[url] = entry
                json_write(saved, manifest)
                if entry.get('http_status') == 429:
                    print('[LIMITADO] HTTP 429; detener recuperación para respetar el servicio.', flush=True)
                    break
                if delay:
                    time.sleep(delay)
        finally:
            context.close()
    return write_inventory(out, manifest)


def main():
    ap = argparse.ArgumentParser(description='Recuperación selectiva y verificable de documentos, iframes y cuestionarios')
    ap.add_argument('--out', type=Path, default=Path('export_pde'))
    ap.add_argument('--profile-dir', default='.google_skills_browser')
    ap.add_argument('--audit-only', action='store_true', help='Solo verificar archivos locales, sin navegador')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--enter-quizzes', action='store_true',
                    help='Opt-in: puede iniciar intentos de quiz; no selecciona ni envía respuestas')
    ap.add_argument('--delay', type=float, default=2.0)
    ap.add_argument('--no-traverse-slides', action='store_true', help='Solo primera pantalla de iframe')
    ap.add_argument('--retry-partial', action='store_true', help='Volver a inspeccionar incluso recursos parciales ya guardados')
    ap.add_argument('--only', choices=['quiz', 'document', 'html_bundle'], help='Recuperar solo esta clase de recurso')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    report = run(args.out, args.profile_dir, headless=args.headless,
                 include_quiz_start=args.enter_quizzes, delay=args.delay,
                 limit=max(0, args.limit), audit_only=args.audit_only,
                 traverse_slides=not args.no_traverse_slides, retry_partial=args.retry_partial,
                 only=args.only)
    print(json.dumps({'total': sum(i['total'] for i in report['resource_totals'].values()),
                      'resource_totals': report['resource_totals'],
                      'complete': report['complete'],
                      'report': str(args.out / 'resource_coverage_report.json')},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
