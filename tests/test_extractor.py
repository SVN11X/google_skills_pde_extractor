import json
from pathlib import Path
from extractor import seed_from_html, extract_page, canonical, extract_youtube_ids, is_learning_url, norm_url

BASE='https://www.skills.google/paths/16'


def test_seed_list():
    modules=[{'steps':[{'activities':[
        {'id':1, 'title':'Lab One','href':'/focuses/2794?parent=catalog&path=16','description':'Prueba'},
        {'id':2, 'title':'Course One','href':'/paths/16/course_templates/1157','description':'Curso de datos'}
    ]}]}]
    html=f'<html><main><h1>Ruta</h1><ql-contents-menu modules=\'{json.dumps(modules)}\'></ql-contents-menu></main></html>'
    seed=seed_from_html(html)
    assert seed['activity_count']==2
    assert seed['activities'][0]['url'].startswith('https://www.skills.google/focuses/2794')
    assert seed['activities'][1]['title']=='Course One'


def test_metadata_and_videos():
    page='''<html><title>Lección</title><main><h1>Pipeline streaming</h1>
    <p>El procedimiento usa Dataflow y Apache Beam.</p>
    <a href='/focuses/123'>Laboratorio</a>
    <iframe src='https://www.youtube.com/embed/dQw4w9WgXcQ'></iframe>
    <img src='https://cdn.qwiklabs.com/image.png' alt='Diagrama'/>
    </main><script>var secret='should not enter saved page'</script></html>'''
    parsed=extract_page(page,BASE)
    assert len(parsed['activities'])==1
    assert len(parsed['videos'])==1
    assert len(parsed['images'])==1
    assert 'Apache Beam' in parsed['markdown']
    assert 'secret' not in parsed['markdown']


def test_link_filters():
    assert canonical('https://www.skills.google/paths/16/course_templates/53')==canonical('https://www.skills.google/course_templates/53')
    assert not is_learning_url('https://www.skills.google/my_account/payments')
    assert norm_url('javascript:alert(1)') is None
    assert extract_youtube_ids('''https://www.youtube.com/watch?v=dQw4w9WgXcQ''',[])==['dQw4w9WgXcQ']


def test_saved_seed_is_13():
    path=Path(__file__).parents[1]/'seed_catalog.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data['activity_count']==13
    assert len(data['activities'])==13
    assert len(set(x['url'].split('?')[0] for x in data['activities']))==13


def test_videos_transcription_and_frames_same_run(monkeypatch, tmp_path):
    """One pass attempts subtitle fallback, Whisper and two-method frames."""
    from extractor import process_videos
    vid='dQw4w9WgXcQ'
    events=[]

    def no_api(video_id, folder):
        events.append('transcript-api')
        return 'Sin transcripcion directa'

    def no_subs(url, folder):
        events.append('yt-dlp-subtitles')
        return 'Sin subtitulos'

    def fake_download(url, folder, *, audio_only=False):
        events.append('download-video')
        source=folder/'source.mp4'
        source.write_bytes(b'test')
        return source, None

    def fake_whisper(source, folder, model):
        events.append('whisper')
        (folder/'transcript.txt').write_text('[0.0s] Hola mundo',encoding='utf-8')
        return None

    def fake_frames(source, folder, seconds, method):
        events.append('frames-'+method)
        target=folder/'frames'/'interval'
        target.mkdir(parents=True)
        (target/'frame_00001.jpg').write_bytes(b'test')
        return None

    monkeypatch.setattr('extractor.yt_fetch_transcript',no_api)
    monkeypatch.setattr('extractor.run_yt_dlp_subtitles',no_subs)
    monkeypatch.setattr('extractor.download_video',fake_download)
    monkeypatch.setattr('extractor.run_whisper',fake_whisper)
    monkeypatch.setattr('extractor.extract_frames',fake_frames)
    pages={'x':{'url':BASE,'videos':[{'id':vid}]}}
    results=process_videos(pages,tmp_path,frames=True,whisper=True,frame_method='both')
    assert results[0]['transcript']=='ok'
    assert results[0]['frames']==1
    assert events==['transcript-api','yt-dlp-subtitles','download-video','whisper','frames-both']
    assert not (tmp_path/'videos'/vid/'source.mp4').exists()


def test_avoid_action_endpoints_but_keep_real_lessons():
    from extractor import is_learning_url
    cases = {
        'https://www.skills.google/paths/16/course_templates/229/video/607609': True,
        'https://www.skills.google/paths/16/course_templates/229/labs/607613': True,
        'https://www.skills.google/paths/16/course_templates/229/video/607609/complete_button': False,
        'https://www.skills.google/paths/16/course_templates/229/enroll': False,
        'https://www.skills.google/paths/16/course_templates/229/quizzes/607615/start': False,
        'https://www.skills.google/paths/16/course_templates/229/course_surveys/0': False,
        'https://www.skills.google/focuses/607613/resume_on_desktop_email?parent=course_template': False,
        'https://www.skills.google/paths/16/course_templates/1157/labs/Limitations': False,
    }
    for address, expected in cases.items():
        assert is_learning_url(address) is expected, address


def test_video_resume_does_not_redownload_completed_work(tmp_path, monkeypatch):
    from extractor import process_videos
    import extractor
    events=[]
    vid='stj830n-1uE'
    folder=tmp_path/'videos'/vid
    (folder/'frames'/'interval').mkdir(parents=True)
    (folder/'frames'/'scene').mkdir(parents=True)
    (folder/'transcript.txt').write_text('[0.0s] Ya descargado')
    (folder/'frames'/'interval'/'frame_00001.jpg').write_bytes(b'jpeg')
    (folder/'frames'/'scene'/'frame_00001.jpg').write_bytes(b'jpeg')
    monkeypatch.setattr(extractor, 'yt_fetch_transcript', lambda *a: events.append('api'))
    monkeypatch.setattr(extractor, 'download_video', lambda *a, **kw: events.append('media'))
    result=process_videos({'a':{'url':'https://www.skills.google/paths/16/course_templates/1157/video/650769',
                               'videos':[{'id':vid}]}},tmp_path,frames=True,whisper=True,frame_method='both')
    assert events == []
    assert result[0]['transcript']=='ok' and result[0]['frames']==2
    assert (tmp_path/'videos_manifest.json').exists()


def test_youtube_dlp_opts_accepts_project_local_runtime(tmp_path, monkeypatch):
    import extractor
    monkeypatch.setattr(extractor, '__file__', str(tmp_path/'extractor.py'))
    tool=tmp_path/'.tools'/'deno'/'deno.exe'
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b'mock')
    monkeypatch.setattr(extractor.sys,'platform','win32')
    assert extractor.youtube_dlp_opts()['js_runtimes']['deno']['path']==str(tool)
