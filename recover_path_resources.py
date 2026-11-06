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
from urllib.parse import urljoin, urlparse

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
            for slide in range(max_slides if traverse_slides else 1):
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
                'visual_files': rec.get('visual_files', []),
                'captured_states': rec.get('captured_states')}
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
    for kind in ('document', 'html_bundle', 'quiz'):
        reasons[kind] = dict(sorted(Counter(
            (r.get('reason') or 'unspecified') for r in audit
            if r['kind'] == kind and r['status'] != 'recovered'
        ).items()))
    report = {'generated_at': timestamp(), 'path': seed.get('source_url') or '',
              'catalog_activities': len(activities), 'activities': activities,
              'resource_totals': per_kind, 'unresolved_reasons': reasons,
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
                            entry.update(collect_embed_text(page, find_bundle_urls(links), out, folder, traverse_slides=traverse_slides))
                        elif kind == 'document':
                            html = page.locator('html').evaluate('(e)=>e.outerHTML', timeout=12000)
                            recent = extract_page(html, url)
                            links = recent.get('links', []) + meta.get('links', [])
                            urls = find_download_urls(links)
                            attempts = []
                            downloaded = None
                            for asset_url in urls[:5]:
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
