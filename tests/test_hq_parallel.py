import json
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upgrade_transcripts as upgrade
from whisper_batch_worker import run_batch


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')


def mk_out(tmp_path, num=3):
    out = tmp_path / 'export_pde'
    items = []
    for index in range(num):
        vid = f'{index:011d}'
        folder = out / 'videos' / vid
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'source.mp4').write_bytes(b'a'*2048)
        (folder/'transcript.txt').write_text('ORIGINAL!', encoding='utf-8')
        items.append({'id': vid})
    write_json(out/'videos_manifest.json', items)
    return out


def fake_factory(log):
    class Model:
        def __init__(self, *args, **kwargs):
            log.append(('init', args, kwargs))
        def transcribe(self, audio, **kwargs):
            log.append(('transcribe', audio, kwargs))
            segment = SimpleNamespace(text='Cloud SQL and BigQuery', start=2, end=7,
                                      avg_logprob=-0.15, no_speech_prob=0.01)
            return [segment], SimpleNamespace(language='en', language_probability=0.98)
    return Model


def test_batch_shared_model_parallel_and_outputs(tmp_path, capsys):
    out = mk_out(tmp_path)
    calls = []
    jobs = [{'id':x['id'], 'folder':str(out/'videos'/x['id']),
             'media':str(out/'videos'/x['id']/'source.mp4')}
            for x in json.loads((out/'videos_manifest.json').read_text())]
    assert run_batch(jobs, model_factory=fake_factory(calls), workers=2,
                     cpu_threads=2, heartbeat=1) == 0
    assert sum(x[0]=='init' for x in calls) == 1
    assert sum(x[0]=='transcribe' for x in calls) == 3
    assert next(x for x in calls if x[0]=='init')[2]['num_workers'] == 2
    for job in jobs:
        folder = Path(job['folder'])
        assert upgrade.is_finished(folder,'large-v3')
        assert (folder/'transcript.txt').read_text() == 'ORIGINAL!'
    assert 'PDE_HQ_EVENT:' in capsys.readouterr().out


def test_batch_failure_isolated_other_videos_continue(tmp_path):
    out = mk_out(tmp_path, 3)
    jobs = [{'id':f'{i:011d}', 'folder':str(out/'videos'/f'{i:011d}'),
             'media':str(out/'videos'/f'{i:011d}'/'source.mp4')} for i in range(3)]
    calls=[]
    def failing(media, folder, model, name, **kw):
        if folder.name == f'{1:011d}':
            raise RuntimeError('Simulated failure')
        from whisper_worker import transcribe_with_model
        transcribe_with_model(media, folder, model, name, **kw)
    assert run_batch(jobs, workers=2, cpu_threads=2,
                     model_factory=fake_factory(calls), transcriber=failing) == 1
    assert upgrade.is_finished(out/'videos'/f'{0:011d}', 'large-v3')
    assert not upgrade.is_finished(out/'videos'/f'{1:011d}', 'large-v3')
    assert upgrade.is_finished(out/'videos'/f'{2:011d}', 'large-v3')


def test_cpu_plan_conservative(monkeypatch):
    monkeypatch.setattr(upgrade.os, 'cpu_count', lambda: 4)
    monkeypatch.setattr(sys.modules['psutil'], 'cpu_count', lambda logical=False: 2)
    monkeypatch.setattr(sys.modules['psutil'], 'virtual_memory', lambda: SimpleNamespace(available=16*1024**3))
    assert upgrade.cpu_plan()[:2] == (1,2)
    assert upgrade.cpu_plan('2', '1')[:2] == (2,1)


def test_upgrade_skip_completed_and_missing(tmp_path):
    out = mk_out(tmp_path, 3)
    folder=out/'videos'/f'{0:011d}'
    write_json(folder/'transcript_hq.json', {'model':'large-v3','segments':[{'text':'OK'}]})
    (folder/'transcript_hq.txt').write_text('OK quality', encoding='utf-8')
    (out/'videos'/f'{1:011d}'/'source.mp4').unlink()
    def fake_runner(cmd, **kw):
        folder = out/'videos'/f'{2:011d}'
        write_json(folder/'transcript_hq.json', {'model':'large-v3','segments':[{'text':'updated'}]})
        (folder/'transcript_hq.txt').write_text('Updated quality',encoding='utf-8')
        from subprocess import CompletedProcess
        return CompletedProcess(cmd,0,stdout='',stderr='')
    code=upgrade.upgrade(out, workers=1, cpu_threads=2, limit=0, runner=fake_runner)
    assert code == 0
    summary=json.loads((out/'hq_upgrade_report.json').read_text())
    assert summary['already_hq'] == 1
    assert summary['missing_local_media'] == 1


def test_cli_help():
    assert upgrade.is_finished is not None


def test_parent_streams_completion_and_writes_report(tmp_path):
    import io
    out = mk_out(tmp_path, 3)
    class FakePopen:
        def __init__(self, command, **kw):
            self.command = command
            events = []
            for i in range(3):
                vid = f'{i:011d}'
                folder = out/'videos'/vid
                write_json(folder/'transcript_hq.json', {
                    'model':'large-v3', 'segments':[{'text':'HQ successful'}]})
                (folder/'transcript_hq.txt').write_text('HQ successful', encoding='utf-8')
                events.append(upgrade.EVENT_PREFIX + json.dumps({'event':'video_ok','id':vid}))
            self.stdout = io.StringIO('\n'.join(events)+'\n')
        def wait(self, timeout=None):
            return 0
        def poll(self):
            return 0
        def kill(self):
            raise AssertionError('No debe terminar un worker ya finalizado')
    assert upgrade.upgrade(out, workers=2, cpu_threads=2, limit=0,
                           popen_factory=FakePopen) == 0
    report=json.loads((out/'hq_upgrade_report.json').read_text())
    assert report['upgraded'] == 3 and report['failed'] == 0
    assert report['workers'] == 2 and report['cpu_threads'] == 2
    for i in range(3):
        assert (out/'videos'/f'{i:011d}'/'transcript.txt').read_text() == 'ORIGINAL!'


def test_shared_worker_subprocess_without_real_ml(tmp_path):
    import shutil, subprocess
    scripts=tmp_path/'scripts'; scripts.mkdir()
    for name in ('whisper_batch_worker.py','whisper_worker.py'):
        shutil.copy(Path(__file__).resolve().parents[1]/name, scripts/name)
    (scripts/'faster_whisper.py').write_text('''
from types import SimpleNamespace
class WhisperModel:
  def __init__(self, *args, **kwargs):
    self.workers=kwargs.get('num_workers')
  def transcribe(self, media, **kwargs):
    s=SimpleNamespace(text='Google Dataflow',start=1.0,end=3.0,avg_logprob=-0.1,no_speech_prob=0.2)
    return [s],SimpleNamespace(language='en',language_probability=1.0)
''',encoding='utf-8')
    out=mk_out(tmp_path,2)
    jobs=[{'id':f'{i:011d}','media':str(out/'videos'/f'{i:011d}'/'source.mp4'),
           'folder':str(out/'videos'/f'{i:011d}')} for i in range(2)]
    p=scripts/'jobs.json'; write_json(p,jobs)
    process=subprocess.run([sys.executable,'-I',str(scripts/'whisper_batch_worker.py'),
        '--jobs-file',str(p),'--workers','2','--cpu-threads','1'],
        capture_output=True,text=True,timeout=15)
    assert process.returncode == 0,process.stdout+process.stderr
    assert process.stdout.count('"event": "video_ok"') == 2
    assert upgrade.is_finished(out/'videos'/f'{1:011d}','large-v3')
