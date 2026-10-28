"""Validated generation publication with one atomic current-pointer switch."""
import json,os,shutil,time,secrets
from pathlib import Path
import xml.etree.ElementTree as ET
from iptv_client.client import atomic_text
import collection
NAMES=('playlist.m3u','epg.xml')

def manifest(public):
    try:return json.loads((Path(public)/'.current/manifest.json').read_text())
    except (OSError,ValueError):return {}

def _link(target,path):
    temp=path.with_name(path.name+'.next-'+secrets.token_hex(16))
    try:temp.symlink_to(target);os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def _write(path,text,previous=None):
    encoded=text.encode('utf-8')
    if previous and previous.is_file() and previous.read_bytes()==encoded:
        os.link(previous,path)
    else:
        with path.open('xb') as out:
            out.write(encoded);out.flush();os.fsync(out.fileno())
        os.chmod(path,0o644)

def _layout(public):
    versions=public/'.versions';versions.mkdir(parents=True,exist_ok=True,mode=0o755);os.chmod(versions,0o755)
    if not (public/'.current').is_symlink():
        baseline=versions/('baseline-'+secrets.token_hex(16));baseline.mkdir(mode=0o755);os.chmod(baseline,0o755)
        for name in NAMES:
            old=public/name
            if old.is_file():shutil.copy2(old,baseline/name)
        _link('.versions/'+baseline.name,public/'.current')
    for name in NAMES:
        alias=public/name;target='.current/'+name
        if alias.is_symlink() and os.readlink(alias)==target:continue
        _link(target,alias)

def validate(files):
    m3u=files['playlist.m3u']
    if not m3u.startswith('#EXTM3U'):raise ValueError('Invalid generated M3U')
    if '#EXTINF:' not in m3u:raise ValueError('Empty channel catalog')
    if 'epg.xml' in files and ET.fromstring(files['epg.xml']).tag!='tv':raise ValueError('Invalid generated XMLTV')

def commit(public,files,metadata,updated):
    public=Path(public);public.mkdir(parents=True,exist_ok=True);os.chmod(public,0o755)
    files=dict(files);old=manifest(public)
    if 'epg.xml' not in files and old.get('source_id')==metadata.get('source_id'):
        previous=public/'.current/epg.xml'
        if previous.exists():files['epg.xml']=previous.read_text(encoding='utf-8')
    validate(files)
    versions=public/'.versions';versions.mkdir(exist_ok=True,mode=0o755);os.chmod(versions,0o755)
    stage=versions/('generation-'+str(time.time_ns())+'-'+secrets.token_hex(16)[:8]);stage.mkdir(mode=0o755);os.chmod(stage,0o755)
    committed=False;previous_version=None
    try:
        for name,text in files.items():
            if name not in NAMES:raise ValueError('Unexpected public artifact')
            _write(stage/name,text,public/'.current'/name)
        stats=collection.measure(stage,old.get('collection',{}),updated)
        meta=dict(metadata,collection=stats,published_at=updated,version=stage.name)
        _write(stage/'manifest.json',json.dumps(meta,ensure_ascii=False))
        _layout(public)
        previous_version=(public/'.current').resolve().name
        _link('.versions/'+stage.name,public/'.current')
        committed=True
    finally:
        if not committed:shutil.rmtree(stage)
    # Cleanup is maintenance, not publication: never report a committed version as failed.
    try:
        keep={stage.name}
        if previous_version:keep.add(previous_version)
        for path in versions.iterdir():
            if path.is_dir() and not path.is_symlink() and path.name not in keep and path.name.startswith(('generation-','baseline-')):
                shutil.rmtree(path)
    except OSError:pass
    return meta
