"""Regression tests for the resume queue and Windows watchdog status."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import io
from contextlib import redirect_stdout
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extractor import START, canonical, plan_resume_queue
import watchdog_runner as watchdog
from watchdog_runner import phase_from_log


class ResumeQueueTests(unittest.TestCase):
    def test_cyclic_saved_links_are_only_queued_once(self):
        a = 'https://www.skills.google/paths/16/course_templates/1157'
        b = 'https://www.skills.google/paths/16/course_templates/218'
        pages = {
            canonical(START): {'url': START, 'activities': [{'url': a}]},
            canonical(a): {'url': a, 'activities': [{'url': b}, {'url': START}]},
            canonical(b): {'url': b, 'activities': [{'url': a}, {'url': b}]},
        }
        seed = {'activities': [{'url': a}]}
        state = {'discovered': {canonical(b): b}}
        queue, enqueue = plan_resume_queue(seed, state, pages)
        urls = list(queue)
        self.assertEqual(len(urls), 3)
        self.assertEqual(set(map(canonical, urls)), set(pages))
        self.assertFalse(enqueue(a))
        self.assertFalse(enqueue(b))
        self.assertFalse(enqueue(START))
        self.assertEqual(len(queue), 3)

    def test_duplicate_and_action_routes_filtered(self):
        a = 'https://www.skills.google/paths/16/course_templates/1157/video/650769'
        seed = {'activities': [{'url': a}, {'url': a + '/complete_button'}]}
        state = {'discovered': {'legacy': 'https://cloud.google.com/bigquery/docs'}}
        queue, _ = plan_resume_queue(seed, state, {}, follow_articles=False)
        self.assertEqual(len(queue), 2)  # path + real video only

    def test_real_saved_state_finishes_planning(self):
        # Optional fixture from user-export, never included in Git or patch.
        state_path = Path(os.environ.get('PDE_TEST_STATE', ''))
        if not state_path.is_file():
            self.skipTest('Optional user export unavailable')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        zip_path = Path(os.environ.get('PDE_TEST_ZIP', ''))
        pages = {}
        if zip_path.is_file():
            with zipfile.ZipFile(zip_path) as z:
                for n in z.namelist():
                    if n.startswith('export_pde/pages/') and n.endswith('/metadata.json'):
                        p = json.loads(z.read(n).decode('utf-8'))
                        if p.get('url') and 'skills.google' in p['url']:
                            pages[canonical(p['url'])] = p
        seed = {'activities': []}
        queue, enqueue = plan_resume_queue(seed, state, pages)
        scanned = set()
        while queue:
            url = queue.popleft()
            key = canonical(url)
            self.assertNotIn(key, scanned)
            scanned.add(key)
            for act in pages.get(key, {}).get('activities', []):
                enqueue(act.get('url'))
        self.assertLessEqual(len(scanned), len(state['discovered']) + len(pages) * 100 + 1)


class WatchdogTests(unittest.TestCase):
    def test_phase_detection_includes_initial_stages(self):
        self.assertEqual(phase_from_log('14:08:31 INFO ETAPA recorriendo_paginas: Retomando el recorrido'), 'recorriendo_paginas')
        self.assertEqual(phase_from_log('14:08:24 INFO ETAPA abriendo_google_skills: Abriendo la página'), 'abriendo_google_skills')
        self.assertEqual(phase_from_log('14:08:32 INFO Página 1/2000: https://www.skills.google'), 'recorriendo_paginas')

    def test_supervisor_accepts_child_interpreter_with_different_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / 'export_pde'
            out.mkdir()
            (root / 'extractor.py').write_text("import json, os, time\nfrom pathlib import Path\nout=Path('export_pde')\n(out/'runtime_status.json').write_text(json.dumps({\n  'pid': os.getpid()+321, 'run_id': os.environ['PDE_RUN_ID'],\n  'phase': 'recorriendo_paginas', 'message':'Preparación de cola terminada'\n}), encoding='utf-8')\ntime.sleep(1.8)\n", encoding='utf-8')
            stages = dict(watchdog.PHASE_LIMITS)
            stages.update({'startup': 1.5, 'recorriendo_paginas': 3.0})
            with mock.patch.multiple(watchdog, ROOT=root, OUT=out,
                LOG=out/'execution.log', INFLIGHT=out/'inflight_page.json',
                SKIPPED=out/'skip_urls.json', STATE=out/'crawl_state.json',
                STATUS=out/'runtime_status.json',
                POLL_SECONDS=0.025, REMINDER_SECONDS=10,
                MAX_RESTARTS=0, PHASE_LIMITS=stages):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(watchdog.run(), 0, output.getvalue())


if __name__ == '__main__':
    unittest.main()
