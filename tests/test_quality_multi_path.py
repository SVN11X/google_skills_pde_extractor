import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upgrade_transcripts as quality
import build_ai_corpus as ai
import multi_path
import extractor


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding='utf8')


def test_parse_path_strict():
    assert multi_path.parse_path('https://www.skills.google/paths/16')[0] == '16'
    assert multi_path.parse_path('321')[1] == 'https://www.skills.google/paths/321'
    for url in ('https://evil.google/paths/16','https://www.skills.google/paths/16?x=1','http://www.skills.google/paths/16'):
        with pytest.raises(ValueError):
            multi_path.parse_path(url)


def test_load_paths_dedup(tmp_path):
    p = tmp_path / 'paths.txt'
    p.write_text('# note\n16\nhttps://www.skills.google/paths/16\n222\n', encoding='utf-8')
    assert len(multi_path.load_paths(p)) == 2


def test_upgrade_reports_missing_media_and_preserves_original(tmp_path):
    out = tmp_path / 'export_pde'
    vid='abcdefghijk'
    write_json(out/'videos_manifest.json', [{'id':vid,'url':'https://www.youtube.com/watch?v='+vid}])
    folder=out/'videos'/vid
    folder.mkdir(parents=True)
    (folder/'transcript.txt').write_text('existing',encoding='utf8')
    code=quality.upgrade(out, runner=lambda *a,**k: None)
    assert code==0
    rep=json.loads((out/'hq_upgrade_report.json').read_text())
    assert rep['missing_local_media']==1
    assert (folder/'transcript.txt').read_text()=='existing'


def test_upgrade_writes_quality_without_overwrite(tmp_path):
    out=tmp_path/'export_pde'
    vid='abcdefghijk'
    write_json(out/'videos_manifest.json', [{'id':vid,'url':'https://www.youtube.com/watch?v='+vid}])
    folder=out/'videos'/vid
    folder.mkdir(parents=True)
    (folder/'source.mp4').write_bytes(b'0'*2048)
    (folder/'transcript.txt').write_text('Original', encoding='utf8')
    def fake_runner(cmd, **kwargs):
        assert cmd[cmd.index('--model')+1]=='large-v3'
        assert cmd[cmd.index('--output-prefix')+1]=='transcript_hq'
        write_json(folder/'transcript_hq.json',{'model':'large-v3','language':'en','segments':[{'text':'New text','start':3,'duration':2}]})
        (folder/'transcript_hq.txt').write_text('HQ text',encoding='utf8')
        return subprocess.CompletedProcess(cmd,0,stdout='',stderr='')
    assert quality.upgrade(out,runner=fake_runner)==0
    assert (folder/'transcript.txt').read_text()=='Original'
    assert quality.upgrade(out,runner=lambda *a,**k: (_ for _ in ()).throw(Exception('No retry')))==0


def test_ai_corpus_prefers_hq(tmp_path):
    out=tmp_path/'export_pde'
    write_json(out/'coverage_report.json', {'path':'https://www.skills.google/paths/16'})
    vid='abcdefghijk'; url='https://www.youtube.com/watch?v='+vid
    write_json(out/'videos_manifest.json', [{'id':vid,'url':url,'sources':['https://www.skills.google/paths/16/course_templates/72']}])
    folder=out/'videos'/vid
    write_json(folder/'transcript.json', {'language':'en', 'segments':[{'text':'original','start':0,'duration':2}]})
    write_json(folder/'transcript_hq.json', {'language':'en','model':'large-v3', 'segments':[{'text':'enhanced','start':4,'duration':3}]})
    (folder/'transcript_hq.txt').write_text('enhanced', encoding='utf8')
    page=out/'pages'/'page_a'
    write_json(page/'metadata.json', {'title':'Course title','url':'https://www.skills.google/paths/16'})
    (page/'content.md').write_text('# Great study guide\n\nLearn Dataflow.',encoding='utf8')
    stats=ai.build(out)
    items=[json.loads(x) for x in (out/'ai_library'/'study_corpus.jsonl').read_text().splitlines()]
    v=next(x for x in items if x['kind']=='video_transcript')
    assert 'enhanced' in v['text'] and 'original' not in v['text']
    assert v['start_seconds']==4 and v['end_seconds']==7
    assert v['timestamp_url'].endswith('&t=4s')
    assert v['provenance']=='whisper_hq' and v['model']=='large-v3'
    assert len(items)>=2 and stats['pages_with_text']==1
    assert (out/'ai_library'/'study_pack_path_16.zip').is_file()


def test_combine_includes_legacy(tmp_path):
    path_root=tmp_path/'root'
    write_json(path_root/'path_111'/'ai_library'/'study_corpus.jsonl',{})
    p=path_root/'path_111'/'ai_library'/'study_corpus.jsonl'
    p.write_text(json.dumps({'id':'one'})+'\n')
    legacy=tmp_path/'export_pde'/'ai_library';legacy.mkdir(parents=True)
    (legacy/'study_corpus.jsonl').write_text(json.dumps({'id':'two'})+'\n')
    assert ai.combine(path_root, legacy.parent)['chunks']==2


def test_path_scope_changes_with_start():
    old=extractor.START
    try:
        extractor.START='https://www.skills.google/paths/432'
        assert extractor.is_learning_url(extractor.START)
        assert extractor.is_learning_url('https://www.skills.google/paths/432/course_templates/72')
        assert not extractor.is_learning_url('https://www.skills.google/paths/16/course_templates/72')
    finally:
        extractor.START=old
