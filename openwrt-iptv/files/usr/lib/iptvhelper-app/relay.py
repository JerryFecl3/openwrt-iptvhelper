"""Manage only the assistant-owned procd relay, never the official UCI service."""
import ipaddress,json,re,socket,subprocess,threading,time,sys
from pathlib import Path
from iptv_client.client import atomic_text
STATE=Path('/var/lib/iptvhelper-app/relay.json')
SERVICE='/etc/init.d/iptvhelper-relay'
PLAYER_PLAYLIST=Path('/etc/iptvhelper-data/media/playlist.m3u')

def run(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL,timeout=15).strip()
def plan(config,device):
    if not device or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}',device):raise ValueError('Invalid upstream device')
    ip=str(ipaddress.IPv4Address(config.get('relay_listen','0.0.0.0')))
    port=str(config.get('relay_port','5141'))
    if not port.isdigit() or not 1<=int(port)<=65535:raise ValueError('Invalid relay port')
    return ['--noconfig','--listen',ip+':'+port,'--upstream-interface',device,
            '--pid-file','/var/run/iptvhelper-relay.pid','--maxclients','3','--workers','1','--verbose','1',
            '--external-m3u','file://'+PLAYER_PLAYLIST.as_posix(),'--external-m3u-update-interval','120']
def available(config):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind((config.get('relay_listen','0.0.0.0'),int(config.get('relay_port','5141'))))
def desired(settings,interface):
    import policy
    config=settings();status=interface(config.get('interface','iptv'));state=policy.read_state()
    if config.get('service_enabled','1')=='0':raise ConnectionError('IPTV assistant disabled')
    device=status.get('l3_device')
    if not status.get('up') or not state.get('up') or state.get('device')!=device or state.get('interface')!=config.get('interface','iptv') or time.time()-state.get('time',0)>20:
        raise ConnectionError('IPTV policy unavailable')
    return config,plan(config,device)
def running():
    return subprocess.run([SERVICE,'running'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10).returncode==0
def start(settings,interface):
    def worker():
        previous=None;last_error=None
        while True:
            try:
                if run('uci','changes','iptvhelper'):
                    time.sleep(5);continue
                config,args=desired(settings,interface)
                active=running()
                if previous is None and active:
                    # On helper restart, compare against the actual procd command.
                    data=json.loads(run('ubus','call','service','list','{"name":"iptvhelper-relay"}'))
                    instances=data.get('iptvhelper-relay',{}).get('instances',{})
                    active=any(v.get('running') and v.get('command')==['/usr/bin/rtp2httpd']+args for v in instances.values())
                if not active or previous is not None and args!=previous:
                    run(SERVICE,'stop');available(config);run(SERVICE,'start')
                previous=args
                atomic_text(STATE,json.dumps({'running':running(),'listen':config.get('relay_listen','0.0.0.0'),'port':config.get('relay_port','5141'),'checked':time.time()}))
                last_error=None
            except Exception as error:
                subprocess.run([SERVICE,'stop'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
                message=str(error) if isinstance(error,(ValueError,ConnectionError,OSError)) else type(error).__name__
                atomic_text(STATE,json.dumps({'running':False,'error':message,'checked':time.time()}))
                if message!=last_error:print('assistant relay: '+message,flush=True)
                previous=None;last_error=message
            time.sleep(10)
    threading.Thread(target=worker,name='assistant-relay',daemon=True).start()
if __name__=='__main__':
    from app import settings,interface
    config,args=desired(settings,interface)
    available(config)
    print(' '.join(args))
