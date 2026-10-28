"""Low-frequency HTTP checks, independent of platform/collection state."""
import json,time,threading,ipaddress
import urllib.request
import xml.etree.ElementTree as ET
from iptv_client.client import atomic_text

KEYS=('m3u','epg','relay','player')

def get(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=5) as r:
        if r.status!=200:raise ValueError('HTTP status')
        data=r.read(24*1024*1024+1)
        if len(data)>24*1024*1024:raise ValueError('Response too large')
        return data

def local_origin(settings):
    host=str(ipaddress.IPv4Address(settings.get('relay_listen','0.0.0.0')))
    if host=='0.0.0.0':host='127.0.0.1'
    port=int(settings.get('relay_port','5141'))
    if not 1<=port<=65535:raise ValueError('Invalid relay port')
    return 'http://'+host+':'+str(port)

def check(settings,fetch=get):
    media=local_origin(settings)
    public=media+'/'
    def m3u():
        body=fetch(public+'playlist.m3u').decode('utf-8-sig')
        return body.startswith('#EXTM3U') and '#EXTINF:' in body
    def epg():
        root=ET.fromstring(fetch(public+'epg.xml'))
        return root.tag=='tv' and root.find('channel') is not None and root.find('programme') is not None
    def relay():return b'<html' in fetch(media+'/status').lower()
    def player():return b'<html' in fetch(media+'/player').lower()
    items={}
    for name,probe in [('m3u',m3u),('epg',epg),('relay',relay),('player',player)]:
        try:items[name]={'ok':bool(probe())}
        except Exception as e:items[name]={'ok':False,'error':type(e).__name__}
    return {'checked':time.time(),'items':items}

def project(value,now=None):
    fresh=0<=(time.time() if now is None else now)-value.get('checked',0)<660
    items={k:{'ok':fresh and bool(value.get('items',{}).get(k,{}).get('ok'))} for k in KEYS}
    return {'ok':all(v['ok'] for v in items.values()),'items':items,'checked':value.get('checked'),'stale':not fresh}

def refresh_interval(result):
    """Retry startup/transient failures promptly; keep healthy checks infrequent."""
    return 300 if all((result or {}).get('items',{}).get(k,{}).get('ok') for k in KEYS) else 15

def start(state,settings):
    def run():
        while True:
            result=None
            try:
                result=check(settings())
                atomic_text(state/'services.json',json.dumps(result))
            except Exception:pass
            time.sleep(refresh_interval(result))
    threading.Thread(target=run,name='service-probes',daemon=True).start()
