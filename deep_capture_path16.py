"""Conservative, resumable deep evidence capture for authenticated Google Skills Path 16.

Only explores the currently selected Articulate Rise lesson from a verified LMS
iframe (or that *same* lesson in a detached tab). No assessment/quiz answers,
submissions, lesson-next actions, scraping hidden DOM, or credential exports.
Existing extraction files and video transcripts are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from recover_path_resources import (
    json_write, live_bundle_urls, page_resources,
    quiz_has_questions, rise_frame_metadata, rise_lesson_id,
    routed_training_urls, safe_lesson_url, sanitized_origin, timestamp,
    training_html_urls,
)

CONTROL_SELECTOR = ', '.join((
    '[role="tab"]', 'summary', 'button[aria-expanded]', 'button[aria-controls]',
    'button[class*="accordion"]', 'button[class*="flip"]',
    'button[class*="labeled-graphic"]', 'button[class*="hotspot"]',
    'button[class*="marker"]', 'button[class*="process"]',
    'button[class*="timeline"]', '.labeled-graphic-marker',
    '.labeled-graphic-pin',
))
# A conservative allow-list: ONLY these controls, located inside a lesson block.
# These exclusions apply even if the control has aria-expanded / aria-controls.
FORBIDDEN_CONTROL = re.compile(
    r'\b(?:start|launch|begin|resume|quiz|test|assessment|exam|submit|check|'
    r'grade|score|answer|reveal correct|retry|reset|finish|complete|'
    r'next|previous|continue|siguiente|enviar|comprobar|respuesta|'
    r'evaluaci[oó]n|examen|finalizar|iniciar)\b', re.I)
QUIZ_BLOCK = re.compile(r'(?:quiz|knowledge.check|assessment|test.question|'
                        r'block-question|block-quiz|graded)', re.I)
IMAGE_HOSTS = {'storage.googleapis.com', 'cdn.qwiklabs.com'}
IMAGE_EXTENSIONS = {'image/png': '.png', 'image/jpeg': '.jpg',
                    'image/webp': '.webp', 'image/gif': '.gif'}
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_VISIBLE_TEXT = 18000


def valid_lesson_match(expected: str | None, observed: str | None) -> bool:
    return bool(expected and expected == observed and re.fullmatch(r'[A-Za-z0-9_-]{12,100}', expected))


def sanitize_image_url(raw: str, origin: str) -> str | None:
    """Only authorized static training images; do not save tokenized query URLs."""
    if not raw or raw.startswith(('data:', 'blob:', 'javascript:')):
        return None
    absolute = urljoin(origin, raw)
    p = urlparse(absolute)
    if (p.scheme != 'https' or (p.hostname or '').lower() not in IMAGE_HOSTS or
            p.username or p.password or not p.path or
            (p.hostname == 'storage.googleapis.com' and '/cls-html5-courses/' not in p.path)):
        return None
    if p.query:  # Avoid signed/ephemeral URLs, and never persist a query string.
        return None
    return sanitized_origin(absolute)


def is_safe_control(meta: dict, *, quiz_block: bool = False) -> bool:
    if quiz_block or not isinstance(meta, dict) or not meta.get('visible'):
        return False
    if meta.get('disabled'):
        return False
    label = ' '.join(str(meta.get(k) or '') for k in ('label', 'title', 'text'))
    return not bool(FORBIDDEN_CONTROL.search(label) or
                    QUIZ_BLOCK.search(str(meta.get('class_hint') or '')))


def needs_visual_repair(entry: dict) -> bool:
    """Only revisit a Rise lesson when the existing log has unpictured states."""
    if entry.get('kind') not in ('document', 'html_bundle'):
        return False
    if not entry.get('lesson_mapping_verified') or not entry.get('evidence_file'):
        return False
    return int(entry.get('states_captured') or 0) > int(entry.get('screenshots_saved') or 0)


def replace_from_staging(out: Path, folder: Path, staging: Path,
                         staged_result: dict) -> dict:
    """Move a better staged capture into place; keep a full original backup."""
    source = staging / 'rise_deep'
    proof_path = source / 'lesson_blocks.json'
    if not proof_path.is_file():
        raise RuntimeError('Staged Rise evidence is incomplete')
    destination = folder / 'rise_deep'
    # Resolve links *before* replacing the original. An error at this stage
    # must not affect prior lesson data.
    proof = _load_json(proof_path)
    if not isinstance(proof.get('blocks'), list):
        raise RuntimeError('Staged Rise block inventory is invalid')
    stage_relative = staging.relative_to(out) / 'rise_deep'
    dest_relative = destination.relative_to(out)
    for block in proof['blocks']:
        for state in block.get('states', []):
            if state.get('screenshot'):
                state['screenshot'] = (
                    dest_relative / Path(state['screenshot']).relative_to(stage_relative)
                ).as_posix()
    json_write(proof_path, proof)

    backup = None
    if destination.exists():
        backups = folder / 'rise_deep_prev'
        backups.mkdir(parents=True, exist_ok=True)
        marker = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = backups / marker
        destination.rename(backup)
    try:
        source.rename(destination)
    except Exception:
        if backup and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    result = dict(staged_result)
    for key in ('content_file', 'evidence_file'):
        if result.get(key):
            relative = Path(result[key]).relative_to(staging.relative_to(out))
            result[key] = (destination.relative_to(out) /
                           relative.relative_to('rise_deep')).as_posix()
    return result


def normalize_visible_text(value: str) -> str:
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n{3,}', '\n\n', value or '')).strip()


def _visible_text(block) -> str:
    try:
        return normalize_visible_text(block.inner_text(timeout=4000))[:MAX_VISIBLE_TEXT]
    except Exception:
        return ''


def _visible_controls(block) -> list[dict]:
    """No hidden HTML or answer values are read; only visible control metadata."""
    try:
        return block.locator(CONTROL_SELECTOR).evaluate_all('''(els) => els.map((el, index) => {
          const style = window.getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          const visible = rect.width > 1 && rect.height > 1 &&
            style.visibility !== 'hidden' && style.display !== 'none';
          return {index, visible, disabled: Boolean(el.disabled ||
            el.getAttribute('aria-disabled') === 'true'),
            class_hint: String(el.className || '').slice(0,180),
            label: (el.getAttribute('aria-label') || '').slice(0,120),
            title: (el.getAttribute('title') || '').slice(0,120),
            text: (el.innerText || '').trim().slice(0,120)};
        })''')
    except Exception:
        return []


def _visible_images(block, lesson_url: str) -> list[dict]:
    try:
        data = block.locator('img').evaluate_all('''imgs => imgs.filter(img => {
            const r=img.getBoundingClientRect();const s=getComputedStyle(img);
            return r.width>2 && r.height>2 && s.display!=='none' && s.visibility!=='hidden';
          }).map(img=>({url:img.currentSrc||img.src||'',alt:(img.alt||'').slice(0,180)}))''')
    except Exception:
        return []
    unique, result = set(), []
    for item in data[:120]:
        clean = sanitize_image_url(item.get('url', ''), lesson_url)
        if clean and clean not in unique:
            unique.add(clean)
            result.append({'source_url': clean, 'alt': item.get('alt', '')})
    return result


def _screenshot(block, dest: Path) -> bool:
    try:
        img = block.screenshot(timeout=7000, animations='disabled')
        if not img or len(img) > 8 * 1024 * 1024:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(img)
        return True
    except Exception:
        return False


def _save_training_images(page, images: list[dict], folder: Path, max_images: int) -> dict:
    """Bounded copies of already-visible <img> resources. No media URLs with queries."""
    count, failures = 0, 0
    for item in images:
        if count >= max_images:
            break
        url = item['source_url']
        try:
            response = page.context.request.get(url, timeout=16000)
            if response.status != 200:
                failures += 1
                continue
            mime = (response.headers.get('content-type') or '').split(';')[0].lower().strip()
            size = int(response.headers.get('content-length') or 0)
            if mime not in IMAGE_EXTENSIONS or size > MAX_IMAGE_BYTES:
                failures += 1
                continue
            raw = response.body()
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                failures += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()[:16]
            name = digest + IMAGE_EXTENSIONS[mime]
            dest = folder / 'images' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file():
                dest.write_bytes(raw)
            item['local_image'] = (Path('images') / name).as_posix()
            count += 1
        except Exception:
            failures += 1
    return {'images_saved': count, 'images_failed': failures,
            'images_limit_reached': len(images) > max_images}


def _blocks(frame) -> list[str]:
    try:
        candidates = frame.locator('main.lesson-main [data-block-id]').evaluate_all('''nodes =>
          [...new Set(nodes.filter(n=> n.getClientRects().length > 0)
          .map(n=>n.getAttribute('data-block-id')).filter(Boolean))]''')
    except Exception:
        return []
    return [x for x in candidates if isinstance(x, str)
            and re.fullmatch(r'[a-zA-Z0-9_-]{6,100}', x)][:300]


def _block_is_quiz(block) -> bool:
    try:
        class_desc = block.evaluate('''el => [el.className, ...Array.from(el.querySelectorAll("[class]"))
          .slice(0,80).map(e=>e.className)].map(String).join(" ")''')
        return bool(QUIZ_BLOCK.search(class_desc))
    except Exception:
        return False


def _read_dialog(frame) -> str:
    """Some Rise hotspots render the opened panel outside the block."""
    try:
        dialogs = frame.locator('[role="dialog"]:visible')
        if dialogs.count():
            return _visible_text(dialogs.last)[:5000]
    except Exception:
        pass
    return ''


def _close_reading_dialog(frame) -> None:
    """Dismiss an opened Rise info overlay; never click evaluation actions."""
    try:
        dialogs = frame.locator('[role="dialog"]:visible')
        if not dialogs.count():
            return
        dialog = dialogs.last
        for label in ('Close', 'Cerrar', 'Dismiss'):
            button = dialog.get_by_role('button', name=re.compile(r'^' + label + r'$', re.I)).first
            if button.count() and button.is_visible():
                button.click(timeout=2000)
                return
        # Escape is a keyboard dismissal only; it never submits a form.
        dialog.press('Escape', timeout=2000)
    except Exception:
        pass


def _visual_bytes(block) -> bytes:
    """Inspect a flipped card's visible rendering without persisting hidden DOM."""
    try:
        image = block.screenshot(timeout=6500, animations='disabled')
        return image if image and len(image) <= 8 * 1024 * 1024 else b''
    except Exception:
        return b''


def capture_lesson(frame, page, lesson_url: str, out: Path, folder: Path,
                   *, max_controls: int = 60, max_screenshots: int = 12,
                   max_images: int = 24) -> dict:
    """Capture *visible* states of the current verified lesson, without navigating away.

    A text/image observation is distinct from proving full coverage. Only
    allow-listed, non-assessment controls are clicked. Every click is bounded.
    """
    route_id = rise_lesson_id(lesson_url)
    if not route_id or not valid_lesson_match(route_id, rise_frame_metadata(frame).get('lesson_id')):
        return {'status': 'partial', 'reason': 'rise_lesson_id_mismatch'}
    details = rise_frame_metadata(frame)
    ids = _blocks(frame)
    evidence_root = folder / 'rise_deep'
    evidence_root.mkdir(parents=True, exist_ok=True)
    collected = []
    markdown = [f'# {details.get("lesson_title") or "Lección Rise"}', '',
                f'Lección de origen: {sanitized_origin(page.url)}',
                f'Identificador Rise: `{route_id}`',
                'Evidencia: texto y estados visibles; no constituye verificación de todas las interacciones.', '']
    seen_images, images = set(), []
    interactions, screenshots, states = 0, 0, 0
    screenshot_failures, screenshot_cap_skips = 0, 0
    incomplete = []
    for block_id in ids:
        if not valid_lesson_match(route_id, rise_frame_metadata(frame).get('lesson_id')):
            incomplete.append('navigation_left_selected_lesson')
            break
        block = frame.locator(f'[data-block-id="{block_id}"]').first
        try:
            block.scroll_into_view_if_needed(timeout=6000)
            page.wait_for_timeout(90)
        except Exception:
            incomplete.append(f'block_not_visible:{block_id}')
            continue
        baseline = _visible_text(block)
        if len(baseline) >= MAX_VISIBLE_TEXT:
            incomplete.append(f'visible_text_truncated:{block_id}')
        controls = _visible_controls(block)
        is_quiz = _block_is_quiz(block)
        record = {'block_id': block_id, 'visible_initial_text_characters': len(baseline),
                  'quiz_like_block': is_quiz, 'controls_detected': len(controls),
                  'controls_safe': sum(is_safe_control(c, quiz_block=is_quiz) for c in controls),
                  'controls_activated': 0, 'unique_states': 1, 'states': [],
                  'images': []}
        markdown.extend([f'## Bloque `{block_id}`', '', baseline or '*(sin texto visible)*', ''])
        initial_images = _visible_images(block, lesson_url)
        for img in initial_images:
            if img['source_url'] not in seen_images:
                seen_images.add(img['source_url']); images.append(img)
            record['images'].append(img['source_url'])
        seen_states = {hashlib.sha256((baseline + repr(record['images'])).encode()).hexdigest()}
        visited_controls = set()
        if is_quiz:
            record['note'] = 'No se pulsa ningún control de evaluación.'
        # Reenumerate after every action: tabs can reveal accordions or cards.
        while not is_quiz:
            controls = _visible_controls(block)
            record['controls_detected'] = max(record['controls_detected'], len(controls))
            record['controls_safe'] = max(record['controls_safe'], sum(
                is_safe_control(c, quiz_block=is_quiz) for c in controls))
            next_control = None
            for control in controls:
                key = (control.get('index'), control.get('label'),
                       control.get('title'), control.get('text'), control.get('class_hint'))
                if key not in visited_controls and is_safe_control(control, quiz_block=is_quiz):
                    next_control = (control, key)
                    break
            if not next_control:
                break
            if interactions >= max_controls:
                incomplete.append('lesson_control_limit_reached')
                break
            control, key = next_control
            visited_controls.add(key)
            if not valid_lesson_match(route_id, rise_frame_metadata(frame).get('lesson_id')):
                incomplete.append('navigation_left_selected_lesson')
                break
            visual_sensitive = bool(re.search(r'flip|card|hotspot|marker|labeled-graphic',
                                              str(key), re.I))
            prior_visual = _visual_bytes(block) if visual_sensitive else b''
            try:
                candidate = block.locator(CONTROL_SELECTOR).nth(control['index'])
                if not candidate.is_visible() or not candidate.is_enabled():
                    continue
                # Only pre-approved reading controls inside a verified block.
                candidate.click(timeout=4200)
                page.wait_for_timeout(140)
                interactions += 1
            except Exception:
                incomplete.append('safe_control_click_failed')
                continue
            record['controls_activated'] += 1
            if not valid_lesson_match(route_id, rise_frame_metadata(frame).get('lesson_id')):
                incomplete.append('navigation_left_selected_lesson')
                break
            changed = _visible_text(block)
            dialog = _read_dialog(frame)
            visible_images = _visible_images(block, lesson_url)
            for img in visible_images:
                if img['source_url'] not in seen_images:
                    seen_images.add(img['source_url']); images.append(img)
                if img['source_url'] not in record['images']:
                    record['images'].append(img['source_url'])
            combined = changed + ('\n\n' + dialog if dialog else '')
            if len(changed) >= MAX_VISIBLE_TEXT:
                incomplete.append(f'visible_text_truncated:{block_id}')
            signature = hashlib.sha256((combined + repr(record['images'])).encode()).hexdigest()
            visual_after = b''
            if signature in seen_states:
                # 3D cards may expose a visual change without changing text.
                if not prior_visual:
                    _close_reading_dialog(frame)
                    continue
                visual_after = _visual_bytes(block)
                if not visual_after or visual_after == prior_visual:
                    _close_reading_dialog(frame)
                    continue
                signature += ':visible_pixels:' + hashlib.sha256(visual_after).hexdigest()

            seen_states.add(signature)
            record['unique_states'] += 1
            states += 1
            name = (control.get('label') or control.get('title') or control.get('text') or
                    f'control {control["index"]}')[:120]
            state = {'control': name, 'visible_text_characters': len(combined)}
            if screenshots < max_screenshots:
                file_path = evidence_root / 'screenshots' / f'{block_id[:32]}_{record["unique_states"]:03d}.png'
                if visual_after:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(visual_after)
                    saved = True
                else:
                    saved = _screenshot(block, file_path)
                if saved:
                    screenshots += 1
                    state['screenshot'] = file_path.relative_to(out).as_posix()
                else:
                    screenshot_failures += 1
                    state['screenshot_status'] = 'failed'
            else:
                screenshot_cap_skips += 1
                state['screenshot_status'] = 'limit_reached'
            record['states'].append(state)
            markdown.extend([f'### Estado visible: {name}', '', combined or '*(sin texto visible)*', ''])
            _close_reading_dialog(frame)
        collected.append(record)
        # Per-block checkpoint in case the browser closes before the next lesson.
        json_write(evidence_root / 'lesson_blocks.partial.json', {
            'lesson_id': route_id, 'blocks': collected, 'checkpoint_only': True})
    if screenshot_cap_skips:
        incomplete.append('screenshot_limit_reached')
    if screenshot_failures:
        incomplete.append('screenshot_capture_failed')
    image_stats = _save_training_images(page, images, evidence_root, max_images)
    for img in images:
        if img.get('local_image'):
            markdown.extend([f'Imagen visible: `{img["local_image"]}`',
                             f'Descripción: {img["alt"]}', ''])
    content_path = evidence_root / 'lesson_content.md'
    content_path.write_text('\n'.join(markdown), encoding='utf-8')
    stats = {'source_url': sanitized_origin(page.url), 'rise_lesson_id': route_id,
             'rise_lesson_route': safe_lesson_url(lesson_url),
             'lesson_title': details.get('lesson_title') or '',
             'block_count_initial': len(ids), 'blocks_visited': len(collected),
             'controls_detected': sum(b['controls_detected'] for b in collected),
             'controls_safe': sum(b['controls_safe'] for b in collected),
             'controls_activated': interactions, 'new_text_states': states,
             'screenshots_saved': screenshots,
             'screenshots_skipped_due_to_limit': screenshot_cap_skips,
             'screenshots_failed': screenshot_failures,
             'visible_image_references': len(images),
             **image_stats, 'blocks': collected, 'limitations': sorted(set(incomplete)),
             'verified_full_coverage': False,
             'note': 'Verificación de ruta Rise y observaciones visibles, no garantía de cobertura exhaustiva.'}
    json_path = evidence_root / 'lesson_blocks.json'
    json_write(json_path, stats)
    (evidence_root / 'lesson_blocks.partial.json').unlink(missing_ok=True)
    return {'status': 'partial', 'reason': 'rise_deep_evidence_captured; completeness_not_proven',
            'lesson_mapping_verified': True, 'lesson_id': route_id,
            'content_file': content_path.relative_to(out).as_posix(),
            'evidence_file': json_path.relative_to(out).as_posix(),
            'blocks_visited': len(collected), 'blocks_detected': len(ids),
            'controls_activated': interactions, 'states_captured': states,
            'screenshots_saved': screenshots, 'images_saved': image_stats['images_saved'],
            'screenshots_skipped_due_to_limit': screenshot_cap_skips,
            'screenshots_failed': screenshot_failures,
            'verified_full_coverage': False}


def _find_rise_frame(page, route: str):
    """Require DOM + hash agreement in the iframe. Detached fallback uses exact route."""
    expected = rise_lesson_id(route)
    for _ in range(8):
        for frame in page.frames:
            if safe_lesson_url(getattr(frame, 'url', '')) != route:
                continue
            if valid_lesson_match(expected, rise_frame_metadata(frame).get('lesson_id')):
                return frame, None
        page.wait_for_timeout(600)
    detached = page.context.new_page()
    try:
        response = detached.goto(route, wait_until='domcontentloaded', timeout=45000)
        if response and response.status in (401, 403, 429):
            detached.close(); return None, None
        for _ in range(14):
            if valid_lesson_match(expected, rise_frame_metadata(detached.main_frame).get('lesson_id')):
                return detached.main_frame, detached
            detached.wait_for_timeout(600)
    except Exception:
        pass
    detached.close()
    return None, None


def _safe_quiz_preview(page, out: Path, folder: Path) -> dict:
    """Never click Start quiz, select an answer, or navigate an assessment."""
    try:
        text = normalize_visible_text(page.locator('main').first.inner_text(timeout=7000))
    except Exception:
        text = ''
    if quiz_has_questions(text):
        path = folder / 'quiz_visible_questions.md'
        path.write_text(text, encoding='utf-8')
        return {'status': 'partial', 'reason': 'questions_visible_without_start; no_answers_submitted',
                'content_file': path.relative_to(out).as_posix(), 'visible_text_chars': len(text)}
    return {'status': 'partial', 'reason': 'quiz_requires_start_or_no_questions_visible',
            'quiz_started': False, 'visible_text_chars': len(text)}


def _load_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


def summarize(entries: dict) -> dict:
    rise = [v for v in entries.values() if v.get('kind') in ('document', 'html_bundle')]
    quiz = [v for v in entries.values() if v.get('kind') == 'quiz']
    return {'generated_at': timestamp(), 'rise_lessons_tried': len(rise),
            'rise_with_deep_evidence': sum(v.get('blocks_visited', 0) > 0 for v in rise),
            'blocks_visited': sum(v.get('blocks_visited', 0) for v in rise),
            'controls_activated': sum(v.get('controls_activated', 0) for v in rise),
            'new_text_states': sum(v.get('states_captured', 0) for v in rise),
            'images_saved': sum(v.get('images_saved', 0) for v in rise),
            'quiz_pages_checked_without_start': len(quiz),
            'quizzes_with_visible_questions': sum(bool(v.get('content_file')) for v in quiz),
            'complete': False,
            'note': 'Los resultados son evidencia nueva. No prueban cobertura exhaustiva.'}


def run(out: Path, profile_dir: str, *, only_url=None, kind='rise',
        limit=0, force=False, headless=False, delay=1.0,
        max_controls=60, max_screenshots=64, max_images=24,
        repair_screenshots=False):
    out = out.resolve()
    if not (out / 'pages').is_dir():
        raise RuntimeError('No existe export_pde/pages; ejecutar la extracción base antes.')
    all_resources = _load_json(out / 'resources_manifest.json')
    targets = page_resources(out)
    def rise_target(item):
        if item['kind'] == 'html_bundle': return True
        if item['kind'] != 'document': return False
        saved = all_resources.get(item['url'], {})
        return saved.get('resource_format') == 'embedded_html_course' or bool(
            training_html_urls(item['source_metadata'].get('links', [])))
    targets = [t for t in targets if (t['kind'] == 'quiz' if kind == 'quiz' else rise_target(t))]
    if repair_screenshots and kind != 'rise':
        raise ValueError('--repair-screenshots solo es compatible con --kind rise')
    if only_url:
        clean = sanitized_origin(only_url)
        if urlparse(clean).hostname != 'www.skills.google':
            raise ValueError('La URL debe pertenecer a www.skills.google')
        targets = [t for t in targets if t['url'] == clean]
        if not targets:
            raise ValueError('El recurso no está presente en el inventario local del Path 16.')
    manifest_path = out / 'rise_deep_manifest.json'
    entries = _load_json(manifest_path)
    if repair_screenshots:
        targets = [t for t in targets if needs_visual_repair(entries.get(t['url'], {}))]
        print(f'[AUDITORÍA] Reparación visual selectiva: {len(targets)} lecciones', flush=True)
        if not targets:
            summary = summarize(entries)
            json_write(out / 'rise_deep_coverage_report.json', summary)
            return summary
    if not targets:
        raise RuntimeError('No se encontraron lecciones Rise o cuestionarios en el inventario local.')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('Instala Playwright con el entorno Python del proyecto.') from exc
    processed = 0
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile_dir, headless=headless,
            viewport={'width': 1365, 'height': 900}, locale='en-US', accept_downloads=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(12000)
        try:
            for i, target in enumerate(targets, 1):
                url, folder = target['url'], target['folder']
                previous = entries.get(url, {})
                if (not force and not repair_screenshots and previous.get('blocks_visited', 0) > 0 and
                        previous.get('evidence_file') and
                        (out / previous['evidence_file']).is_file()):
                    print(f'[{i}/{len(targets)}] YA CAPTURADO: {url}', flush=True)
                    continue
                if (not force and kind == 'quiz' and previous.get('kind') == 'quiz' and
                        previous.get('reason') in ('quiz_requires_start_or_no_questions_visible',
                                                    'questions_visible_without_start; no_answers_submitted') and
                        (not previous.get('content_file') or (out / previous['content_file']).is_file())):
                    print(f'[{i}/{len(targets)}] QUIZ YA INSPECCIONADO (sin iniciar): {url}', flush=True)
                    continue
                if limit and processed >= limit: break
                processed += 1
                result = {'source_url': url, 'kind': target['kind'],
                          'status': 'partial', 'checked_at': timestamp()}
                print(f'[{i}/{len(targets)}] INSPECCIONANDO: {url}', flush=True)
                detached = None
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=50000)
                    if response and response.status in (401, 403, 429):
                        result['reason'] = f'HTTP_{response.status}_access_restricted'
                    elif response and response.status >= 400:
                        result['reason'] = f'HTTP_{response.status}'
                    elif urlparse(page.url).hostname != 'www.skills.google':
                        result['reason'] = 'not_on_authorized_lms'
                    elif target['kind'] == 'quiz':
                        result.update(_safe_quiz_preview(page, out, folder))
                    else:
                        page.wait_for_timeout(500)
                        trusted = list(dict.fromkeys(live_bundle_urls(page)))
                        # Keep the hash read from the LIVE iframe. Persisted URLs
                        # only help disambiguate when they match this entrypoint.
                        routes = routed_training_urls(page, trusted)
                        if len(routes) != 1:
                            result['reason'] = 'expected_exactly_one_live_rise_lesson_route'
                        else:
                            route = routes[0]
                            saved_route = safe_lesson_url(all_resources.get(url, {}).get('lesson_route') or '')
                            if saved_route and saved_route != route:
                                result['reason'] = 'live_rise_route_conflicts_with_previous_verification'
                            else:
                                frame, detached = _find_rise_frame(page, route)
                                if frame is None:
                                    result['reason'] = 'rise_iframe_and_detached_route_unverified'
                                else:
                                    if repair_screenshots:
                                        # Isolated staging avoids overwriting a good prior capture
                                        # if an image fails or the live page changes between runs.
                                        with tempfile.TemporaryDirectory(prefix='_rise_repair_', dir=folder) as temp:
                                            stage = Path(temp)
                                            fresh = capture_lesson(frame, page, route, out, stage,
                                                max_controls=max_controls,
                                                max_screenshots=max_screenshots,
                                                max_images=max_images)
                                            improved = (fresh.get('evidence_file') and
                                                fresh.get('blocks_visited', 0) >= previous.get('blocks_visited', 0) and
                                                fresh.get('states_captured', 0) >= previous.get('states_captured', 0) and
                                                fresh.get('screenshots_saved', 0) > previous.get('screenshots_saved', 0) and
                                                fresh.get('images_saved', 0) >= previous.get('images_saved', 0))
                                            if improved:
                                                result.update(replace_from_staging(out, folder, stage, fresh))
                                            else:
                                                result = dict(previous)
                                                print('  [CONSERVADO] Nueva captura sin mejora verificable; '
                                                      'se retiene la anterior.', flush=True)
                                    else:
                                        result.update(capture_lesson(frame, page, route, out, folder,
                                            max_controls=max_controls, max_screenshots=max_screenshots,
                                            max_images=max_images))
                                    print(f'  Rise: bloques={result.get("blocks_visited",0)} '
                                          f'estados nuevos={result.get("states_captured",0)} '
                                          f'controles={result.get("controls_activated",0)}', flush=True)
                except Exception as exc:
                    result['reason'] = 'capture_error_' + type(exc).__name__
                finally:
                    if detached is not None:
                        detached.close()
                # Never replace an earlier good run with a transient network error.
                if previous.get('evidence_file') and not result.get('evidence_file'):
                    result = previous
                entries[url] = result
                json_write(manifest_path, entries)
                if result.get('reason', '').startswith('HTTP_429'):
                    print('HTTP 429: pausa obligatoria; no reintentar hasta que el servicio lo permita.')
                    break
                if delay: time.sleep(delay)
        finally:
            context.close()
    summary = summarize(entries)
    json_write(out / 'rise_deep_coverage_report.json', summary)
    return summary


def main():
    ap = argparse.ArgumentParser(description='Evidencia profunda y segura de Rise: Path 16')
    ap.add_argument('--out', type=Path, default=Path('export_pde'))
    ap.add_argument('--profile-dir', default='.google_skills_browser')
    ap.add_argument('--kind', choices=['rise', 'quiz'], default='rise')
    ap.add_argument('--only-url')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--delay', type=float, default=1.0)
    ap.add_argument('--max-controls', type=int, default=60)
    ap.add_argument('--max-screenshots', type=int, default=64)
    ap.add_argument('--repair-screenshots', action='store_true',
                    help='Reintentar solo Rise con estados sin captura; respaldar original')
    ap.add_argument('--max-images', type=int, default=24)
    args = ap.parse_args()
    report = run(args.out, args.profile_dir, only_url=args.only_url, kind=args.kind,
                 limit=max(0,args.limit), force=args.force, headless=args.headless,
                 delay=max(0,args.delay), max_controls=max(0,args.max_controls),
                 max_screenshots=max(0,args.max_screenshots), max_images=max(0,args.max_images),
                 repair_screenshots=args.repair_screenshots)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
