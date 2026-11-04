"""Supervisor de Google Skills PDE: progreso visible, reanudación y límites por fase.

No elude accesos ni modifica el progreso de los cursos. Termina únicamente el proceso
hijo creado por este supervisor si deja de responder. No borra la extracción previa.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'export_pde'
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / 'execution.log'
INFLIGHT = OUT / 'inflight_page.json'
SKIPPED = OUT / 'skip_urls.json'
STATE = OUT / 'crawl_state.json'
STATUS = OUT / 'runtime_status.json'

MAX_RESTARTS = 3
STARTUP_IDLE_SECONDS = 180
PREPARING_IDLE_SECONDS = 300
PAGE_IDLE_SECONDS = 210
IMAGE_IDLE_SECONDS = 900
VIDEO_IDLE_SECONDS = 3600
POLL_SECONDS = 5
REMINDER_SECONDS = 45

PHASE_LIMITS = {
    'startup': STARTUP_IDLE_SECONDS,
    'preparando': PREPARING_IDLE_SECONDS,
    'cargando_estado': PREPARING_IDLE_SECONDS,
    'abriendo_chrome': STARTUP_IDLE_SECONDS,
    'abriendo_google_skills': STARTUP_IDLE_SECONDS,
    'recorriendo_paginas': PAGE_IDLE_SECONDS,
    'descargando_imagenes': IMAGE_IDLE_SECONDS,
    'procesando_videos': VIDEO_IDLE_SECONDS,
    'finalizado': STARTUP_IDLE_SECONDS,
}


def json_save(path: Path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def json_load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def mark_inflight_timeout():
    current = json_load(INFLIGHT, {})
    key, url = current.get('key'), current.get('url')
    if not key or not url:
        return None
    skipped = json_load(SKIPPED, {})
    if not isinstance(skipped, dict):
        skipped = {k: {'url': k, 'reason': 'Timeout previo'} for k in skipped}
    skipped[key] = {
        'url': url,
        'reason': 'Sin progreso; omitida para continuar el resto',
        'at': datetime.now(timezone.utc).isoformat(),
    }
    json_save(SKIPPED, skipped)
    state = json_load(STATE, {'visited': {}, 'discovered': {}})
    state.setdefault('visited', {})[key] = {
        'url': url, 'status': 'timeout_skipped',
        'error': 'Se omitió tras agotar el tiempo de espera; revisar manualmente',
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }
    json_save(STATE, state)
    INFLIGHT.unlink(missing_ok=True)
    return url


def terminate_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                       timeout=30)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(0.25)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        pass


def read_new_lines(path, previous_size):
    if not path.exists():
        return previous_size, []
    current_size = path.stat().st_size
    if current_size < previous_size:
        previous_size = 0
    if current_size == previous_size:
        return current_size, []
    with path.open('rb') as fh:
        fh.seek(previous_size)
        content = fh.read(current_size - previous_size).decode('utf-8', 'replace')
    return current_size, content.splitlines()


def phase_from_log(line):
    if re.search(r'\bPágina \d+/', line):
        return 'recorriendo_paginas'
    if 'Descargando imágenes' in line or 'Imágenes ' in line:
        return 'descargando_imagenes'
    if re.search(r'\b(?:Procesando video|Video) \d+/', line):
        return 'procesando_videos'
    return None


def run():
    print('\n=== CONTINUACIÓN SUPERVISADA GOOGLE SKILLS PDE ===', flush=True)
    print('Conserva export_pde y .google_skills_browser: NO se borrará tu avance.', flush=True)
    print('Se informará si Chrome, la sesión o la lectura de datos se bloquean.', flush=True)
    flags = ['--all', '--retry-failed', '--max-pages', '2000', '--delay', '2',
             '--frame-method', 'both', '--frame-seconds', '10']

    for restart in range(MAX_RESTARTS + 1):
        start_size = LOG.stat().st_size if LOG.exists() else 0
        STATUS.unlink(missing_ok=True)  # evitar confundir fases de ejecuciones anteriores
        command = [sys.executable, '-u', str(ROOT / 'extractor.py'), *flags]
        kwargs = {'cwd': str(ROOT)}
        if os.name != 'nt':
            kwargs['start_new_session'] = True
        print(f'\n[Intento {restart + 1}/{MAX_RESTARTS + 1}] Iniciando Python...', flush=True)
        proc = subprocess.Popen(command, **kwargs)
        print(f'[PID {proc.pid}] Buscando avances guardados y abriendo navegador.', flush=True)
        phase = 'startup'
        last_activity = time.monotonic()
        last_notice = last_activity
        timed_out = False
        try:
            while proc.poll() is None:
                time.sleep(POLL_SECONDS)
                clock = time.monotonic()
                start_size, new_lines = read_new_lines(LOG, start_size)
                if new_lines:
                    last_activity = clock
                    for line in new_lines:
                        found = phase_from_log(line)
                        if found:
                            phase = found
                status = json_load(STATUS, {})
                if status.get('pid') == proc.pid and status.get('phase'):
                    next_phase = status['phase']
                    if next_phase != phase:
                        phase = next_phase
                        last_activity = clock
                        print(f"[ESTADO] {status.get('message') or next_phase}", flush=True)
                        last_notice = clock
                idle = clock - last_activity
                if phase == 'esperando_login':
                    if clock - last_notice >= REMINDER_SECONDS:
                        print('[LOGIN] Inicia sesión en Chrome y pulsa ENTER en esta consola; '
                              'el proceso espera tu intervención.', flush=True)
                        last_notice = clock
                    continue
                threshold = PHASE_LIMITS.get(phase, STARTUP_IDLE_SECONDS)
                if clock - last_notice >= REMINDER_SECONDS:
                    print(f'[SUPERVISOR] Fase {phase}; sin novedades desde hace {int(idle)} s '
                          f'(límite {threshold} s).', flush=True)
                    last_notice = clock
                if idle > threshold:
                    timed_out = True
                    print(f'[BLOQUEO] Sin progreso durante {int(idle)} s en «{phase}».', flush=True)
                    terminate_tree(proc)
                    if phase == 'recorriendo_paginas':
                        skipped = mark_inflight_timeout()
                        if skipped:
                            print(f'[PÁGINA OMITIDA] {skipped}', flush=True)
                    else:
                        print('[DIAGNÓSTICO] Si Chrome no abre, cierra SOLO las ventanas del '
                              'extractor anterior. No borres el perfil ni los datos.', flush=True)
                    break
        except KeyboardInterrupt:
            print('\n[DETENIDO] Se conservaron los archivos de export_pde.', flush=True)
            terminate_tree(proc)
            return 130
        code = proc.poll()
        if code == 0:
            print('\n[OK] Terminado. Informe: export_pde\\coverage_report.json', flush=True)
            return 0
        if restart >= MAX_RESTARTS:
            print('\n[ERROR] Se agotaron los reintentos. '
                  'Revisa export_pde\\execution.log y runtime_status.json.', flush=True)
            return 1
        if not timed_out:
            print(f'[ERROR] El extractor terminó con código {code}. '
                  'Reintentando sin borrar datos.', flush=True)
        print('[REANUDANDO] Se utilizará el progreso guardado.', flush=True)
        time.sleep(3)
    return 1


if __name__ == '__main__':
    sys.exit(run())
