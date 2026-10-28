"""Layer-two publication snapshot; content hashes ignore generation metadata."""
import hashlib,json,re
import xml.etree.ElementTree as ET
from iptv_client.client import atomic_text

def digest(items):
    return hashlib.sha256(json.dumps(sorted(items),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def record(state,public,updated):
    path=state/'collection.json'
    try:old=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):old={}
    snapshot=measure(public,old,updated)
    atomic_text(path,json.dumps(snapshot,ensure_ascii=False))
    return snapshot

def measure(public,old,updated):
    live=[];catchup=[];info=None
    for line in (public/'playlist.m3u').read_text(encoding='utf-8').splitlines():
        if line.startswith('#EXTINF:'):info=line
        elif line and not line.startswith('#') and info:
            attrs=dict(re.findall(r'([\w-]+)="([^"]*)"',info))
            identity=[attrs.get('tvg-id',''),info.rsplit(',',1)[-1]]
            live.append(json.dumps([identity,re.sub(r'\s+catchup[\w-]*="[^"]*"','',info),line],ensure_ascii=False))
            if attrs.get('catchup-source'):
                catchup.append(json.dumps([identity,{k:v for k,v in attrs.items() if k.startswith('catchup')}],sort_keys=True,ensure_ascii=False))
            info=None
    root=ET.parse(public/'epg.xml').getroot() if (public/'epg.xml').exists() else ET.Element('tv')
    programmes=root.findall('programme')
    epg=[ET.tostring(e,encoding='unicode').strip() for e in root if e.tag in ('channel','programme')]
    snapshot={'updated':updated}
    for key,items,count in [('live',live,len(live)),('catchup',catchup,len(catchup)),('epg',epg,len(programmes))]:
        hashed=digest(items);previous=old.get(key,{})
        snapshot[key]={'count':count,'hash':hashed,'changed':previous.get('changed') if previous.get('hash')==hashed else updated}
    return snapshot


def project(snapshot,last,readiness=None):
    phase=last.get('previous_phase') if last.get('phase')=='running' else last.get('phase')
    if readiness=='ready' and phase=='network_unavailable':
        # An unstarted attempt is not a failed collection. Older versions
        # persisted this transient condition over the previous task status.
        phase=None if last.get('accepted') is False else 'failed'
    status='network_unavailable' if phase=='network_unavailable' else 'failed' if phase=='failed' or phase=='degraded' and last.get('epg_status')=='failed' else 'partial' if phase=='degraded' else 'collected' if snapshot else 'empty'
    if readiness=='network_unavailable':status='network_unavailable'
    return {'status':status,'running':last.get('phase')=='running','updated':snapshot.get('updated'),
            **{k:{x:snapshot.get(k,{}).get(x) for x in ('count','changed')} for k in ('live','catchup','epg')}}
