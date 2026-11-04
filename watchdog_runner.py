"""Supervisor de progreso para el extractor Google Skills.

No evade restricciones: detecta trabajos bloqueados, termina SOLO el proceso que inició
para este extractor, registra la URL responsable y reanuda con su estado persistido.
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
# Los documentos externos no se recorren en modo --all. No bloquea tu inicio de sesión.
MAX_RESTARTS = 3
PAGE_IDLE_SECONDS = 210
IMAGE_IDLE_SECONDS = 900
VIDEO_IDLE_SECONDS = 3600  # Whisper y FFmpeg pueden requerir bastante CPU.
POLL_SECONDS = 5


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
    current = json_load(INFLIGHT,{})
    key, url = current.get('key'), current.get('url')
    if not key or not url:
        return None
    skipped=json_load(SKIPPED,{})
    if not isinstance(skipped,dict):
        skipped={k:{'url':k,'reason':'Timeout en ejecución anterior'} for k in skipped}
    skipped[key]={'url':url,'reason':'Navegación sin avance: interrupción de seguridad y salto de URL',
                  'at':datetime.now(timezone.utc).isoformat()}
    json_save(SKIPPED,skipped)
    state=json_load(STATE,{'visited':{},'discovered':{}})
    state.setdefault('visited',{})[key]={'url':url,'status':'timeout_skipped',
        'error':'Se omitió después de bloquear el navegador; pendiente de revisión manual',
        'checked_at':datetime.now(timezone.utc).isoformat()}
    json_save(STATE,state)
    INFLIGHT.unlink(missing_ok=True)
    return url


def terminate_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    else:
        try: os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        time.sleep(2)
        if proc.poll() is None:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
    try: proc.wait(timeout=8)
    except subprocess.TimeoutExpired:pass


def read_new_lines(path, previous_size):
    if not path.exists():return previous_size,[]
    current_size=path.stat().st_size
    if current_size < previous_size: previous_size=0
    if current_size==previous_size:return current_size,[]
    with path.open('rb') as file:
        file.seek(previous_size)
        content=file.read(current_size-previous_size).decode('utf-8','replace')
    return current_size,content.splitlines()


def run():
    print('\n=== CONTINUACIÓN SEGURA GOOGLE SKILLS PDE ===',flush=True)
    print('Se usarán los datos ya existentes de export_pde. Los artículos externos',flush=True)
    print('quedarán como enlaces, sin abrir cientos de páginas de documentación.',flush=True)
    flags=['--all','--retry-failed','--max-pages','2000','--delay','2',
           '--frame-method','both','--frame-seconds','10']
    for restart in range(MAX_RESTARTS+1):
        start_size=LOG.stat().st_size if LOG.exists() else 0
        kwargs={'cwd':str(ROOT)}
        if os.name != 'nt': kwargs['start_new_session']=True
        command=[sys.executable,str(ROOT/'extractor.py'),*flags]
        print(f'\n[Intento {restart+1}/{MAX_RESTARTS+1}] Iniciando... ',flush=True)
        proc=subprocess.Popen(command,**kwargs)
        last_growth=time.monotonic()
        detected_phase='startup'
        started_work=False
        timed_out=False
        try:
            while proc.poll() is None:
                time.sleep(POLL_SECONDS)
                start_size,new_lines=read_new_lines(LOG,start_size)
                if new_lines:
                    last_growth=time.monotonic()
                    for line in new_lines:
                        if re.search(r'\bPágina \d+/',line):
                            detected_phase='page';started_work=True
                        elif 'Descargando imágenes' in line or 'Imágenes ' in line:
                            detected_phase='images';started_work=True
                        elif re.search(r'\b(?:Procesando video|Video) \d+/',line):
                            detected_phase='video';started_work=True
                if not started_work:
                    continue  # La persona puede estar iniciando sesión.
                idle=time.monotonic()-last_growth
                threshold={'page':PAGE_IDLE_SECONDS,'images':IMAGE_IDLE_SECONDS,
                           'video':VIDEO_IDLE_SECONDS}.get(detected_phase,PAGE_IDLE_SECONDS)
                if idle>threshold:
                    timed_out=True
                    print(f'\n[PROTECCIÓN] Sin actividad {int(idle)} s durante {detected_phase}.',flush=True)
                    terminate_tree(proc)
                    if detected_phase=='page':
                        skipped=mark_inflight_timeout()
                        if skipped: print(f'[OMITIDA] {skipped}',flush=True)
                    break
        except KeyboardInterrupt:
            print('\n[DETENIDO] Se conservaron los archivos de export_pde.',flush=True)
            terminate_tree(proc)
            return 130
        code=proc.poll()
        if code == 0:
            print('\n[OK] Ejecución terminada. Consulte export_pde\\coverage_report.json',flush=True)
            return 0
        if restart>=MAX_RESTARTS:
            print('\n[ERROR] Se agotaron los reintentos de protección. No se borraron datos.',flush=True)
            return 1
        print('[REANUDANDO] Estado guardado; se volverá a intentar lo pendiente.',flush=True)
        time.sleep(3)
    return 1


if __name__=='__main__':
    sys.exit(run())
