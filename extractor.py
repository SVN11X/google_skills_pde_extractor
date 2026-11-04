"""Google Skills PDE inventory + opt-in authorized learning-material backup.

Runs locally in the user's own browser profile. No CAPTCHA, login, paywall, or DRM bypass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as to_markdown

BASE = 'https://www.skills.google'
START = BASE + '/paths/16'
UA = 'PDE-Study-Archiver/1.0 (interactive browser; personal study)'
COURSE_PATHS = ('/course_templates/', '/focuses/', '/labs/', '/modules/', '/courses/', '/games/')
AVOID = ('/users/', '/my_account/', '/profile/', '/payments/', '/subscriptions/', '/admin/', '/auth/', '/sessions/', '/freetrial/')
YOUTUBE_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
YOUTUBE_IN_TEXT = re.compile(r'(?:https?:)?//(?:www\.)?(?:youtube\.com/(?:watch\?[^\s"\'<>]*?v=|embed/|shorts/|live/)|youtu\.be/|youtube-nocookie\.com/embed/)([A-Za-z0-9_-]{11})')
GOOD_IMAGE_HOSTS = ('cdn.qwiklabs.com', 'storage.googleapis.com', 'lh3.googleusercontent.com', 'images.unsplash.com')
LOG = logging.getLogger('skills-archiver')
# Endpoints de acciones, no de material. No visitarlos para no modificar progreso.
ACTION_ENDPOINT = re.compile(
    r'/(?:enroll|complete_button|start|badge|resume_on_desktop_email)(?:/|$)'
    r'|/course_surveys(?:/|$)', re.I)



def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def json_write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def set_runtime_phase(out: Path, phase: str, message: str):
    """Publish a human-readable, per-process status for the watchdog.

    This stores no cookies, authentication data, URLs with secrets or browser state.
    """
    json_write(out / 'runtime_status.json', {
        'pid': os.getpid(), 'phase': phase, 'message': message, 'at': now(),
    })
    LOG.info('ETAPA %s: %s', phase, message)


def slug(s: str, limit=72):
    s = re.sub(r'[^a-zA-Z0-9._-]+', '-', s.strip()).strip('-.')
    return (s or 'page')[:limit]


def page_key(url: str):
    p = urlparse(url)
    return slug(p.path.strip('/').replace('/', '__'), 130) or 'path-16'


def norm_url(value: str, origin: str = START) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith(('#', 'javascript:', 'data:', 'mailto:', 'tel:', 'blob:')):
        return None
    url = urljoin(origin, value)
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        return None
    # Strip URL fragments, preserving link-specific query parameters.
    return urlunparse((p.scheme, p.netloc.lower(), p.path or '/', p.params, p.query, ''))


def canonical(url: str) -> str:
    p = urlparse(url)
    # Deduplicate contextual paths like /paths/16/course_templates/53 and /course_templates/53.
    path = re.sub(r'^/paths/\d+(?=/course_templates/)', '', p.path)
    if p.hostname == 'www.skills.google' and ('/focuses/' in path or '/course_templates/' in path):
        return f'{p.scheme}://{p.netloc}{path}'
    if p.hostname == 'www.skills.google':
        return f'{p.scheme}://{p.netloc}{path}'
    return url


def is_learning_url(url: str) -> bool:
    p = urlparse(url)
    if p.hostname != 'www.skills.google' or any(p.path.startswith(a) for a in AVOID):
        return False
    if ACTION_ENDPOINT.search(p.path):
        return False
    # Los laboratorios internos utilizan IDs numéricos; excluir URLs falsas creadas por texto.
    if re.search(r'/labs/([^/]+)', p.path) and not re.search(r'/labs/\d+(?:/|$)', p.path):
        return False
    return (p.path == '/paths/16' or any(x in p.path for x in COURSE_PATHS))


def is_public_article_url(url: str) -> bool:
    p = urlparse(url)
    if p.hostname not in ('cloud.google.com', 'docs.cloud.google.com'):
        return False
    return p.path.startswith(('/docs/', '/blog/', '/learn/', '/architecture/', '/dataflow/', '/bigquery/', '/pubsub/'))


def links_and_embeds(soup: BeautifulSoup, url: str):
    result = {}
    for el in soup.select('[href], [src], [data-src], [poster], [data-url]'):
        tag = el.name or ''
        if tag in ('script', 'link'):
            continue
        for name in ('href', 'src', 'data-src', 'poster', 'data-url'):
            value = el.get(name)
            uri = norm_url(value, url)
            if not uri: continue
            relation = 'link' if name in ('href', 'data-url') else ('image' if tag == 'img' else 'media')
            result[(uri, relation)] = dict(url=uri, kind=relation, label=el.get('aria-label') or el.get('alt') or el.get_text(' ',strip=True)[:200], tag=tag)
    for el in soup.select('[srcset], [data-srcset]'):
        for attr in ('srcset','data-srcset'):
            if not el.get(attr):continue
            for fragment in el.get(attr).split(','):
                uri = norm_url(fragment.strip().split(' ')[0], url)
                if uri: result[(uri, 'image')] = dict(url=uri, kind='image', label=el.get('alt') or '', tag=el.name)
    for el in soup.select('[style]'):
        for fragment in re.findall(r'url\(\s*[\'\"]?([^\)\'\"]+)', el.get('style','')):
            uri=norm_url(fragment,url)
            if uri: result[(uri,'image')] = dict(url=uri, kind='image', label=el.get('alt') or '', tag=el.name)
    return list(result.values())


def json_tree(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values(): yield from json_tree(value)
    elif isinstance(obj, list):
        for value in obj: yield from json_tree(value)


def extract_youtube_ids(text: str, links: list[dict]):
    ids = set(YOUTUBE_IN_TEXT.findall(text))
    for item in links:
        u = urlparse(item['url'])
        host = (u.hostname or '').lower()
        v = None
        if host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
            if u.path == '/watch': v = (parse_qs(u.query).get('v') or [None])[0]
            elif u.path.startswith(('/embed/','/shorts/','/live/')): v = u.path.split('/')[2]
        elif host in ('youtu.be','www.youtu.be','youtube-nocookie.com','www.youtube-nocookie.com'):
            v = u.path.strip('/').split('/')[-1]
        if v and YOUTUBE_ID.fullmatch(v): ids.add(v)
    return sorted(ids)


def extract_page(html: str, url: str, *, follow_articles=False, extra_resources=None) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('main') or soup.select_one('article') or soup.select_one('[role="main"]') or soup.body or soup
    # Avoid exporting accounts, CSRF, analytics, cookies or hidden credential-like metadata.
    safe_main = BeautifulSoup(str(main), 'html.parser')
    for el in safe_main.select('script,style,form,nav,footer,header,input,button,[type="hidden"],.lab-credentials,.credentials-card,#lab-credentials,[data-testid*="credential"]'):
        el.decompose()
    heading = safe_main.find('h1') or safe_main.find('h2')
    title = heading.get_text(' ',strip=True) if heading else (soup.title.get_text(' ',strip=True) if soup.title else url)
    description = ''
    meta_desc = soup.select_one('meta[name="description"]')
    if meta_desc: description = meta_desc.get('content','')

    rich_activity = []
    raw_embedded_urls = []
    has_modules = bool(soup.select('[modules]'))
    for el in soup.select('[modules], [lessons], [activities], script[type="application/ld+json"]'):
        # Prefer the actual path menu to sometimes-outdated JSON-LD course aliases.
        if has_modules and el.name == 'script' and urlparse(url).path == '/paths/16':
            continue
        attrs = [el.get(a) for a in ('modules','lessons','activities') if el.get(a)]
        if el.name == 'script':attrs.append(el.string or el.get_text())
        for payload in attrs:
            try: obj = json.loads(payload)
            except (ValueError,TypeError): continue
            for node in json_tree(obj):
                label = str(node.get('title') or node.get('name') or '').strip()
                address = node.get('href') or node.get('url')
                if isinstance(address,str):
                    child = norm_url(address, url)
                    if child:
                        raw_embedded_urls.append(child)
                        if label and (is_learning_url(child) or is_public_article_url(child)):
                            rich_activity.append({'title':label, 'url':child, 'description':BeautifulSoup(str(node.get('description') or ''),'html.parser').get_text(' ',strip=True), 'is_locked':bool(node.get('isLocked',False)), 'id':node.get('id')})

    link_items = links_and_embeds(safe_main, url)
    # Open-shadow-DOM links/embeds captured by Playwright, which page.content() may omit.
    for extra in extra_resources or []:
        uri=norm_url(extra.get('url'),url)
        if not uri:continue
        kind=extra.get('kind','link')
        if (uri,kind) not in {(x['url'],x['kind']) for x in link_items}:
            link_items.append({'url':uri,'kind':kind,'label':str(extra.get('label') or '')[:200],'tag':'shadow-dom'})
    for link in raw_embedded_urls:
        if link not in [x['url'] for x in link_items]:link_items.append({'url':link,'kind':'structured-link','label':'','tag':'json'})
    # Some meaningful links are directly on ql elements, not only ordinary <a>.
    child_urls=[]
    for item in link_items:
        address=item['url']
        if is_learning_url(address) and canonical(address)!=canonical(url): child_urls.append(address)
        elif follow_articles and is_public_article_url(address):child_urls.append(address)
    # Dedup while keeping source order and preserving path-context URLs.
    visited=set(); child_urls=[u for u in child_urls if not (canonical(u) in visited or visited.add(canonical(u)))]
    acts={}
    for act in rich_activity:
        acts.setdefault(canonical(act['url']),act)
    for address in child_urls:
        acts.setdefault(canonical(address),{'title':'','url':address,'description':'','is_locked':False,'id':None})

    images=[x for x in link_items if x['kind']=='image' and urlparse(x['url']).scheme=='https']
    # Browser HTML may contain YouTube data in player configuration or JSON attrs.
    player_markup = str(main).replace('\\u002F','/').replace('\\/','/')
    videos = extract_youtube_ids(player_markup + ' '.join(str(a) for a in raw_embedded_urls),link_items)
    videos = sorted(set(videos) | set(re.findall(r"(?:youtubeId|youtube_id|videoId|video_id)[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_-]{11})", player_markup)))
    markdown = to_markdown(str(safe_main),heading_style='ATX',bullets='-',strip=['img'])
    markdown = re.sub(r'\n{4,}', '\n\n\n', markdown).strip()
    return {'url':url,'title':title,'description':description,'extracted_at':now(),
            'activities':list(acts.values()),'links':link_items,'images':images,
            'videos':[{'id':v,'url':'https://www.youtube.com/watch?v='+v} for v in videos],
            'markdown':markdown,'text_length':len(safe_main.get_text(' ',strip=True))}


def seed_from_html(html: str) -> dict:
    page=extract_page(html,START)
    # The /paths/16 activity list is authoritative for this saved user's snapshot.
    main=BeautifulSoup(html,'html.parser').select_one('main')
    ordered=[]
    for el in (main.select('[modules]') if main else []):
        try: obj=json.loads(el['modules'])
        except Exception:continue
        for node in json_tree(obj):
            if node.get('title') and node.get('href'):
                u=norm_url(node['href'],START)
                if u and is_learning_url(u):
                    ordered.append({'id':node.get('id'), 'title':node['title'].strip(), 'url':u,
                                    'description':BeautifulSoup(str(node.get('description') or ''),'html.parser').get_text(' ',strip=True),
                                    'is_locked':bool(node.get('isLocked',False))})
    filtered=list({canonical(x['url']):x for x in ordered}.values())
    return {'source_url':START,'source':'HTML guardado por el usuario; inventario inicial, no contenido descargado',
            'extracted_at':now(), 'title':page['title'], 'activity_count':len(filtered),
            'activities':filtered}


def save_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as fh:
        w=csv.DictWriter(fh,fieldnames=fields,extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def write_page(out: Path, page: dict):
    folder=out/'pages'/page_key(page['url'])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'content.md').write_text(f"# {page['title']}\n\nOrigen: {page['url']}\n\n"+page['markdown']+'\n',encoding='utf-8')
    slim={k:v for k,v in page.items() if k!='markdown'}
    json_write(folder/'metadata.json',slim)
    return folder


def download_images(context, pages: dict, out: Path, sleep: float):
    imgs={}
    for p in pages.values():
        for item in p.get('images',[]):
            address=item['url']; host=urlparse(address).hostname or ''
            if host not in GOOD_IMAGE_HOSTS:continue
            imgs.setdefault(address,[]).append(p['url'])
    prior_manifest = {}
    manifest_path = out/'images_manifest.json'
    if manifest_path.exists():
        try:
            prior_manifest = {x['url']: x for x in json.loads(manifest_path.read_text(encoding='utf-8'))}
        except (ValueError, KeyError, OSError):
            pass
    entries=[]
    for index,(u,referrers) in enumerate(imgs.items(),1):
        previous = prior_manifest.get(u)
        if previous and previous.get('file') and (out / previous['file'].replace('\\', '/')).is_file():
            entries.append({**previous,'sources':referrers})
            continue
        p=urlparse(u)
        ext=Path(p.path).suffix.lower().strip('.')
        if ext not in ('jpg','jpeg','png','webp','svg','gif'):ext='bin'
        name=f'{index:04d}_{hashlib.sha256(u.encode()).hexdigest()[:12]}.{ext}'
        target=out/'assets'/'images'/name
        status='ok'
        try:
            r=context.request.get(u,timeout=20000)
            ctype=(r.headers.get('content-type') or '').lower()
            length=len(r.body())
            if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
            if not ctype.startswith('image/') or length>20*1024*1024:
                raise RuntimeError(f'Contenido no-imagen o tamaño >20 MB: {ctype}, {length}')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(r.body())
        except Exception as exc:
            target=None;status=f'failed: {type(exc).__name__} {str(exc)[:140]}'
        entries.append({'url':u,'sources':referrers,'file':str(target.relative_to(out)) if target else None,'status':status})
        if index%10==0:LOG.info('Imágenes %s/%s',index,len(imgs))
        if sleep:time.sleep(sleep)
    json_write(out/'images_manifest.json',entries)
    return entries


def youtube_dlp_opts():
    # yt-dlp >= 2025.11.12 requiere un runtime JS y EJS para recuperar
    # de manera fiable muchos formatos de YouTube. No eludir restricciones.
    local = Path(__file__).resolve().parent / '.tools' / 'deno' / ('deno.exe' if sys.platform == 'win32' else 'deno')
    deno = str(local) if local.is_file() else shutil.which('deno')
    opts = {'remote_components': []}
    if deno:
        opts['js_runtimes'] = {'deno': {'path': deno}}
    return opts


def run_yt_dlp_subtitles(url: str, folder: Path):
    try:
        import yt_dlp
    except ImportError:
        return 'yt-dlp no instalado'
    folder.mkdir(parents=True,exist_ok=True)
    opts={
        'skip_download':True,'writesubtitles':True,'writeautomaticsub':True,
        'subtitleslangs':['en.*','es.*'], 'subtitlesformat':'vtt/srt/best',
        'outtmpl':str(folder/'%(id)s.%(ext)s'),'quiet':True, 'no_warnings':True,
        'ignoreerrors':False,'noplaylist':True,'retries':2,'fragment_retries':2,
        'socket_timeout':20,'sleep_interval_requests':1.0,
        **youtube_dlp_opts()
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:ydl.download([url])
    except Exception as exc:
        return f'{type(exc).__name__}: {str(exc)[:400]}'
    return None


def yt_fetch_transcript(video_id: str, folder:Path):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError: return 'youtube-transcript-api no instalado'
    try:
        api = YouTubeTranscriptApi()
        try:
            transcript=api.fetch(video_id,languages=['en','es','en-US','es-419'])
        except Exception as preferred_error:
            # Si las pistas en inglés/español no existen, buscar una pista pública
            # de otro idioma antes de dar el video por no transcrito.
            try:
                available=api.list(video_id)
                first=next(iter(available), None)
                if first is None: raise preferred_error
                transcript=first.fetch()
            except Exception:
                raise preferred_error
        entries=[{'text':s.text,'start':s.start,'duration':s.duration} for s in transcript]
        if not entries:raise RuntimeError('Transcripción vacía')
        json_write(folder/'transcript.json',{'video_id':video_id,'language':getattr(transcript,'language_code',None),'segments':entries})
        (folder/'transcript.txt').write_text('\n'.join(f"[{e['start']:.1f}s] {e['text']}" for e in entries)+'\n',encoding='utf-8')
        return None
    except Exception as exc:
        return f'{type(exc).__name__}: {str(exc)[:300]}'


def vtt_to_text(folder:Path):
    from html import unescape
    subtitles=sorted(folder.glob('*.vtt')) or sorted(folder.glob('*.srt'))
    if not subtitles:return False
    # Extract readable text without duplicating consecutive caption rollups.
    text=subtitles[0].read_text(encoding='utf-8-sig', errors='replace')
    cues=[]; last=''
    for line in text.splitlines():
        line=line.strip()
        if not line or '-->' in line or line.startswith(('WEBVTT','Kind:','Language:','NOTE','STYLE','REGION')) or line.isdigit(): continue
        line=unescape(re.sub(r'<[^>]+>','',line))
        if line != last:cues.append(line)
        last=line
    (folder/'transcript.txt').write_text('\n'.join(cues)+'\n',encoding='utf-8')
    return True


def download_video(url: str, folder:Path, *, audio_only=False):
    try:import yt_dlp
    except ImportError:return None,'yt-dlp no instalado'
    try:
        opts={'format':'bestaudio[ext=m4a]/bestaudio/best' if audio_only else 'bv*[height<=720]+ba/b[height<=720]/best',
              'outtmpl':str(folder/'source.%(ext)s'),'noplaylist':True,
              'quiet':True,'no_warnings':True,'retries':2,'fragment_retries':2,
              'socket_timeout':30,'continuedl':True,'merge_output_format':'mp4',
              'sleep_interval_requests':1.5,
              **youtube_dlp_opts()}
        ffmpeg=resolve_ffmpeg()
        if ffmpeg:opts['ffmpeg_location']=ffmpeg
        with yt_dlp.YoutubeDL(opts) as ydl:ydl.download([url])
        files=[f for f in folder.glob('source.*') if f.suffix.lower() not in ('.part','.ytdl')]
        return files[0] if files else None, None if files else 'No se descargó archivo'
    except Exception as exc:return None,f'{type(exc).__name__}: {str(exc)[:300]}'


def run_whisper(audio:Path,folder:Path,model_name:str):
    try:from faster_whisper import WhisperModel
    except ImportError:return 'faster-whisper no instalado'
    try:
        model=WhisperModel(model_name,device='auto',compute_type='int8')
        segments,info=model.transcribe(str(audio),beam_size=5, vad_filter=True)
        items=[{'text':x.text.strip(),'start':x.start,'duration':x.end-x.start} for x in segments]
        json_write(folder/'transcript.json',{'language':info.language,'segments':items,'method':'faster-whisper'})
        (folder/'transcript.txt').write_text('\n'.join(f"[{e['start']:.1f}s] {e['text']}" for e in items)+'\n',encoding='utf-8')
        return None
    except Exception as exc:return f'{type(exc).__name__}: {str(exc)[:300]}'


def resolve_ffmpeg():
    """Use system FFmpeg or the binary installed alongside Python (Windows-friendly)."""
    system = shutil.which('ffmpeg')
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


def extract_frames(source: Path, folder: Path, seconds: int, method: str):
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return 'FFmpeg no disponible: instala imageio-ffmpeg o agrega ffmpeg al PATH'
    frame_folder = folder / 'frames'
    frame_folder.mkdir(parents=True, exist_ok=True)
    # A timed sequence plus scene boundaries reduces the risk of missing slides.
    methods = ['interval', 'scene'] if method == 'both' else [method]
    problems = []
    for selected in methods:
        target = frame_folder / selected if method == 'both' else frame_folder
        target.mkdir(parents=True, exist_ok=True)
        if list(target.glob('frame_*.jpg')):
            continue  # Resume without re-extracting an already successful set.
        vf = f'fps=1/{seconds}' if selected == 'interval' else r'select=gt(scene\,0.22)'
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(source), '-vf', vf, '-vsync', 'vfr', '-q:v', '3',
               str(target / 'frame_%05d.jpg')]
        try:
            result = subprocess.run(cmd, timeout=3600, capture_output=True, text=True)
            if result.returncode:
                problems.append(f'{selected}: {(result.stderr or "ffmpeg error")[-400:]}')
            elif not list(target.glob('frame_*.jpg')):
                problems.append(f'{selected}: no se produjeron capturas')
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f'{selected}: {exc}')
    return '; '.join(problems) if problems else None


def has_authenticated_session(page):
    """Conservative UI check; never reads cookies or exports authentication tokens."""
    try:
        return page.locator('#my_account, ql-avatar, a[href*="users/sign_out"]').count() > 0
    except Exception:
        return False


def process_videos(pages:dict,out:Path,frames=False,whisper=False,model='small',keep_videos=False,frame_seconds=10,frame_method='interval'):
    videos={}
    for p in pages.values():
        for vid in p.get('videos',[]):videos.setdefault(vid['id'],set()).add(p['url'])
    results=[]
    for i,(vid,sources) in enumerate(videos.items(),1):
        LOG.info('Procesando video %s/%s: %s',i,len(videos),vid)
        folder=out/'videos'/vid;folder.mkdir(parents=True,exist_ok=True)
        u='https://www.youtube.com/watch?v='+vid
        log=[]
        existing_transcript=folder/'transcript.txt'
        transcript_ok=existing_transcript.is_file() and existing_transcript.stat().st_size>3
        existing_frames=len(list((folder/'frames').rglob('frame_*.jpg')))
        # Necesitamos ambas modalidades si se solicitó --frame-method both.
        frame_sets=['interval','scene'] if frame_method=='both' else [frame_method]
        frames_complete=all(any((folder/'frames'/name if frame_method=='both' else folder/'frames').glob('frame_*.jpg')) for name in frame_sets) if frames else True
        if not transcript_ok and (list(folder.glob('*.vtt')) or list(folder.glob('*.srt'))):
            vtt_to_text(folder)
            transcript_ok=existing_transcript.exists() and existing_transcript.stat().st_size>3
        if not transcript_ok:
            err=yt_fetch_transcript(vid,folder)
            if err:
                log.append('API transcripción: '+err)
                err=run_yt_dlp_subtitles(u,folder)
                if err:log.append('yt-dlp subtítulos: '+err)
                else:vtt_to_text(folder)
            transcript_ok=existing_transcript.exists() and existing_transcript.stat().st_size>3
        need_media=(frames and not frames_complete) or (whisper and not transcript_ok)
        media=None
        if need_media:
            candidates=[x for x in folder.glob('source.*') if x.suffix.lower() not in ('.part','.ytdl','.json')]
            if candidates:media=candidates[0]
            else:
                media,err=download_video(u,folder,audio_only=not (frames and not frames_complete))
                if err:log.append('video/audio: '+err)
        if whisper and not transcript_ok and media:
            err=run_whisper(media,folder,model)
            if err:log.append('Whisper: '+err)
            transcript_ok=existing_transcript.exists() and existing_transcript.stat().st_size>3
        if frames and media and not frames_complete:
            err=extract_frames(media,folder,frame_seconds,frame_method)
            if err:log.append('frames: '+err)
        frame_count=len(list((folder/'frames').rglob('frame_*.jpg')))
        if media and not keep_videos:media.unlink(missing_ok=True)
        entry={'id':vid,'url':u,'sources':sorted(sources),'transcript':'ok' if transcript_ok else 'unavailable',
               'frames':frame_count,'notes':log,'checked_at':now()}
        json_write(folder/'manifest.json',entry)
        results.append(entry)
        # Guardar avance también si se interrumpe la extracción por videos largos.
        json_write(out/'videos_manifest.json',results)
        LOG.info('Video %s/%s: %s, %d frames',i,len(videos),entry['transcript'],frame_count)
    return results


def main_cli():
    ap=argparse.ArgumentParser(description='Extrae enlaces, cursos, texto, imágenes y videos públicos/accesibles de Google Skills PDE')
    ap.add_argument('--out',default='export_pde',help='Carpeta de salida')
    ap.add_argument('--seed-html',help='HTML de la ruta guardado desde Chrome; opcional')
    ap.add_argument('--seed-file',default=str(Path(__file__).with_name('seed_catalog.json')))
    ap.add_argument('--offline-seed-only',action='store_true',help='Solo inventario desde HTML semilla, sin navegador ni red')
    ap.add_argument('--headless',action='store_true',help='No mostrar navegador (primero usar modo visible para iniciar sesión)')
    ap.add_argument('--login-only',action='store_true',help='Abrir navegador para iniciar sesión y guardar perfil persistente; no extrae')
    ap.add_argument('--login-if-needed',action='store_true',help='En la misma ejecución, ofrecer inicio de sesión si la cuenta no está conectada')
    ap.add_argument('--all',action='store_true',help='Activar textos, artículos, imágenes, capturas de páginas, videos, subtítulos, Whisper y capturas de video')
    ap.add_argument('--profile-dir',default='.google_skills_browser',help='Carpeta local de perfil Playwright (nunca subir a Git)')
    ap.add_argument('--download-images',action='store_true',help='Descargar imágenes desde hosts conocidos')
    ap.add_argument('--page-screenshots',action='store_true',help='Capturar pantalla larga de cada página')
    ap.add_argument('--frames',action='store_true',help='Descargar videos accesibles para extraer fotogramas con FFmpeg')
    ap.add_argument('--whisper',action='store_true',help='Si faltan subtítulos, usar Faster-Whisper local con audio accesible')
    ap.add_argument('--whisper-model',default='small')
    ap.add_argument('--keep-videos',action='store_true')
    ap.add_argument('--frame-seconds',type=int,default=10)
    ap.add_argument('--frame-method',choices=['interval','scene','both'],default='both')
    ap.add_argument('--follow-public-articles',action='store_true',help='Seguir enlaces públicos a documentación cloud.google.com')
    ap.add_argument('--max-pages',type=int,default=2000)
    ap.add_argument('--delay',type=float,default=1.7,help='Pausa respetuosa entre cargas')
    ap.add_argument('--retry-failed',action='store_true')
    ap.add_argument('--refresh',action='store_true',help='Volver a visitar URLs exitosas de una ejecución anterior')
    ap.add_argument('--skip-video',action='store_true',help='Solo inventariar URLs de video, no buscar subtítulos ni frames')
    args=ap.parse_args()
    if args.all:
        args.download_images = True
        args.page_screenshots = True
        args.frames = True
        args.whisper = True
        # Enlaces externos se registran, pero NO se siguen automáticamente: \n        # documentación Google Cloud enlaza miles de artículos y puede atascar Chrome.
        # Use --follow-public-articles explícitamente para recorrer documentación pública.
        args.login_if_needed = True
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',datefmt='%H:%M:%S')
    if args.max_pages<1 or args.frame_seconds<1 or args.delay<0:ap.error('max-pages y frame-seconds >= 1; delay >= 0')
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    file_handler=logging.FileHandler(out/'execution.log',encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(file_handler)
    set_runtime_phase(out, 'preparando', 'Leyendo catálogo y comprobando avance anterior')
    seed={}
    if args.seed_html:
        seed=seed_from_html(Path(args.seed_html).read_text(encoding='utf-8-sig'))
        json_write(out/'seed_catalog.json',seed)
    elif Path(args.seed_file).exists():seed=json.loads(Path(args.seed_file).read_text(encoding='utf-8'))
    if seed:
        save_csv(out/'initial_catalog.csv',seed['activities'],['id','title','url','description','is_locked'])
        json_write(out/'initial_catalog.json',seed)
    if args.offline_seed_only:
        json_write(out/'coverage_report.json',{
            'path':START,'status':'seed_only','updated_at':now(),
            'seed_activity_count':len(seed.get('activities',[])),
            'pages_successful':0,'pages_visited':0,
            'pending_discovered_urls':[x['url'] for x in seed.get('activities',[])],
            'note':'Solo inventario; cursos, laboratorios, imágenes internas y transcripciones aún no visitados.'})
        LOG.info('Semilla procesada: %s actividades; contenido interno no descargado',len(seed.get('activities',[])))
        return
    try:from playwright.sync_api import sync_playwright,TimeoutError as PWTimeout
    except ImportError:
        LOG.error('Falta Playwright: pip install -r requirements.txt && python -m playwright install chromium')
        raise SystemExit(2)

    set_runtime_phase(out, 'cargando_estado', 'Cargando páginas ya guardadas sin descargarlas de nuevo')
    state_path=out/'crawl_state.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'visited':{},'discovered':{},'created_at':now()}
    pages={}
    for d in (out/'pages').glob('*/metadata.json'):
        try:
            p=json.loads(d.read_text(encoding='utf-8'))
            # Excluir páginas externas legadas del inventario actual (sin borrarlas).
            if p.get('url') and is_learning_url(p['url']):pages[canonical(p['url'])]=p
        except Exception:pass
    targets=deque([START]+[x['url'] for x in seed.get('activities',[])])
    for address in list(state.get('discovered',{}).values()):
        if is_learning_url(address) or (args.follow_public_articles and is_public_article_url(address)):
            targets.append(address)
    state.setdefault('visited',{});state.setdefault('discovered',{})
    skip_path=out/'skip_urls.json'
    skip_data=json.loads(skip_path.read_text(encoding='utf-8')) if skip_path.exists() else {}
    skip_keys=set(skip_data.keys()) if isinstance(skip_data,dict) else set(skip_data)
    inflight_path=out/'inflight_page.json'
    set_runtime_phase(out, 'abriendo_chrome', 'Iniciando Chromium con el perfil local; cierra instancias anteriores del extractor si se bloquea')

    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(args.profile_dir,headless=args.headless,
                            viewport={'width':1365,'height':900},accept_downloads=False,locale='en-US')
        page=context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15000)
        set_runtime_phase(out, 'abriendo_google_skills', 'Abriendo la página inicial para comprobar la sesión')
        if args.login_only or args.login_if_needed:
            page.goto(START,wait_until='domcontentloaded',timeout=60000)
            page.wait_for_timeout(1600)
            if args.login_only or not has_authenticated_session(page):
                print('\nGoogle Skills: inicia sesión en el navegador abierto si quieres extraer contenido de tu cuenta.')
                print('Cuando hayas terminado de iniciar sesión, pulsa ENTER aquí para continuar la extracción.\n', flush=True)
                set_runtime_phase(out, 'esperando_login', 'Acción del usuario requerida: iniciar sesión en Chrome y pulsar ENTER en la consola')
                try: input()
                except EOFError: LOG.warning('Sin consola interactiva; se continúa con recursos públicos')
                page.wait_for_timeout(1000)
                if not has_authenticated_session(page):
                    LOG.warning('No se confirmó sesión iniciada. Algunas lecciones podrían quedar inaccesibles.')
            if args.login_only:
                context.close();return
        set_runtime_phase(out, 'recorriendo_paginas', f'Retomando el recorrido; {len(pages)} páginas recuperadas del disco')
        seen_now=set(); attempts=0
        while targets and attempts<args.max_pages:
            u=targets.popleft();key=canonical(u)
            if not (is_learning_url(u) or (args.follow_public_articles and is_public_article_url(u))):
                continue
            if key in seen_now or key in skip_keys:continue
            prior=state['visited'].get(key,{}).get('status')
            if (prior=='ok' and not args.refresh) or (prior and prior!='ok' and not args.retry_failed and not args.refresh):
                if key in pages:
                    for child in pages[key].get('activities',[]):
                        child_url=child['url']
                        if is_learning_url(child_url) or (args.follow_public_articles and is_public_article_url(child_url)):
                            targets.append(child_url)
                continue
            seen_now.add(key);attempts+=1
            json_write(inflight_path, {'url':u, 'key':key, 'started_at':now()})
            LOG.info('Página %d/%d: %s',attempts,args.max_pages,u)
            record={'url':u,'checked_at':now(),'status':'error'}
            try:
                response=page.goto(u,wait_until='domcontentloaded',timeout=45000)
                status=response.status if response else 0
                record['http_status']=status
                if status in (401,403,429,503):
                    record['status']='restricted' if status!=401 else 'auth_required'
                    record['error']=f'HTTP {status}; no se intenta eludir restricciones'
                    LOG.warning('%s en %s',record['error'],u)
                elif status>=400:
                    record['error']=f'HTTP {status}'
                else:
                    page.wait_for_timeout(1000)
                    # Scroll for lazy assets. Do not auto-click start/quiz/launch buttons.
                    for offset in (0,900,2000,4500):
                        page.locator('body').evaluate('(el,y) => window.scrollTo(0,y)',offset,timeout=12000)
                        page.wait_for_timeout(250)
                    page.locator('body').evaluate('(el) => window.scrollTo(0,0)',timeout=12000)
                    html=page.locator('html').evaluate('(el) => el.outerHTML',timeout=12000)
                    try:
                        shadow_resources=page.locator('body').evaluate("""(bodyEl) => {
                           const out=[];
                           const root=bodyEl.querySelector('main') || bodyEl.querySelector('article') || bodyEl;
                           function scan(node) {
                             if (!node) return;
                             for (const el of node.querySelectorAll('*')) {
                               for (const attr of ['href','src','data-src','poster']) {
                                 const v=el.getAttribute(attr);
                                 if (v) out.push({url:v,kind:attr==='href'?'link':el.tagName==='IMG'?'image':'media',label:el.getAttribute('alt')||el.getAttribute('aria-label')||''});
                               }
                               if (el.shadowRoot) scan(el.shadowRoot);
                             }
                           }
                           scan(root); return out.slice(0,10000);
                        }""", timeout=12000)
                    except Exception:
                        shadow_resources=[]
                    p=extract_page(html,u,follow_articles=args.follow_public_articles,extra_resources=shadow_resources)
                    has_content=p['text_length']>80 or len(p['activities'])>0
                    auth_signals=('sign in to access' in html.lower() or 'sign in to view' in html.lower())
                    if not has_content:
                        record['status']='auth_required' if auth_signals else 'partial'
                        record['error']='No se encontró contenido significativo en la página'
                    else:
                        folder=write_page(out,p)
                        try:
                            rendered=page.locator('main').inner_text(timeout=5000)
                            if len(rendered)>len(p['markdown'])*1.2:
                                (folder/'rendered_text.txt').write_text(rendered,encoding='utf-8')
                        except Exception:pass
                        if args.page_screenshots:
                            try:page.screenshot(path=str(folder/'screenshot.png'),full_page=True,timeout=30000)
                            except Exception as e:record['screenshot_error']=str(e)[:200]
                        pages[key]={k:v for k,v in p.items() if k!='markdown'}
                        record['status']='ok' if p['text_length']>200 or p['activities'] else 'partial'
                        if '/course_templates/' in urlparse(u).path and not p['activities']:
                            record['status']='partial'
                            record['warning']='Se encontró el curso, pero no se pudieron verificar los enlaces de todas sus lecciones/labs.'
                        record['title']=p['title'];record['found_activities']=len(p['activities']);record['found_videos']=len(p['videos'])
                        for act in p['activities']:
                            address=act['url']
                            if is_public_article_url(u): continue  # Don't recursively mirror the documentation website.
                            if not (is_learning_url(address) or args.follow_public_articles and is_public_article_url(address)):continue
                            dest=canonical(address)
                            state['discovered'][dest]=address
                            if dest not in seen_now:targets.append(address)
                    if status in (200,301,302) and p.get('title','').lower().startswith('sign in'):
                        record['status']='auth_required';record['error']='Sitio solicita inicio de sesión'
            except (Exception,) as exc:
                record['status']='error';record['error']=f'{type(exc).__name__}: {str(exc)[:500]}'
                LOG.warning('Error en %s: %s',u,record['error'])
            state['visited'][key]=record
            state['updated_at']=now()
            json_write(state_path,state)
            inflight_path.unlink(missing_ok=True)
            if args.delay:time.sleep(args.delay)
        if args.download_images:
            set_runtime_phase(out, 'descargando_imagenes', 'Reutilizando imágenes descargadas y buscando las pendientes')
            LOG.info('Descargando imágenes de fuentes permitidas...')
            download_images(context,pages,out,args.delay)
        context.close()

    inflight_path.unlink(missing_ok=True)
    set_runtime_phase(out, 'procesando_videos', 'Procesando videos, subtítulos, Whisper y fotogramas')
    video_results=[] if args.skip_video else process_videos(pages,out,frames=args.frames,whisper=args.whisper,
                                 model=args.whisper_model,keep_videos=args.keep_videos,
                                 frame_seconds=args.frame_seconds,frame_method=args.frame_method)
    course_rows=[];external=[];image_refs=[]
    for p in pages.values():
        for a in p.get('activities',[]):course_rows.append({'source_page':p['url'],**a})
        for link in p.get('links',[]):
            if not is_learning_url(link['url']):external.append({'source_page':p['url'],**link})
        for im in p.get('images',[]):image_refs.append({'source_page':p['url'],**im})
    save_csv(out/'all_activities.csv',course_rows,['source_page','title','url','description','is_locked','id'])
    save_csv(out/'all_links.csv',external,['source_page','url','kind','label','tag'])
    save_csv(out/'all_image_urls.csv',image_refs,['source_page','url','kind','label','tag'])
    allowed=lambda u: is_learning_url(u) or (args.follow_public_articles and is_public_article_url(u))
    relevant=[v for v in state['visited'].values() if allowed(v['url'])]
    done=sum(1 for v in relevant if v['status']=='ok')
    failed=[v for v in relevant if v['status']!='ok']
    unvisited=[u for k,u in state['discovered'].items() if allowed(u) and k not in state['visited']]
    ignored_legacy=sum(1 for v in state['visited'].values() if not allowed(v['url']))
    ids_found={v['id'] for p in pages.values() for v in p.get('videos',[])}
    report={'path':START,'updated_at':now(),'seed_activity_count':len(seed.get('activities',[])),
            'pages_successful':done,'pages_with_issues':len(failed),'pages_visited':len(relevant),
            'ignored_old_action_or_out_of_scope_urls':ignored_legacy,
            'skipped_hung_urls':list(skip_data.values()) if isinstance(skip_data,dict) else skip_data,
            'pending_discovered_urls':unvisited,'issues':failed,'youtube_videos_found':len(ids_found),
            'youtube_transcripts_obtained':sum(x['transcript']=='ok' for x in video_results),
            'frames_obtained':sum(x['frames'] for x in video_results),
            'youtube_videos_with_frames':sum(x['frames']>0 for x in video_results),
            'youtube_videos_without_transcription':[x['url'] for x in video_results if x['transcript']!='ok'],
            'youtube_videos_without_frames':[x['url'] for x in video_results if x['frames']<1],
            'note':'Un archivo inicial no demuestra cobertura total. Ver issues y pending_discovered_urls.'}
    json_write(out/'coverage_report.json',report)
    print(f"Terminado. Páginas OK: {done}; con incidencias: {len(failed)}; videos: {len(video_results)}; transcripciones: {report['youtube_transcripts_obtained']}; pendientes: {len(unvisited)}")
    print('Informe:',out/'coverage_report.json')
    set_runtime_phase(out, 'finalizado', 'Extracción terminada; revisar coverage_report.json')


if __name__ == '__main__':main_cli()
