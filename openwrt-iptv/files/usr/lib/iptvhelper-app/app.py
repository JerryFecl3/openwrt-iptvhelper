#!/usr/bin/python3
"""LuCI application layer. No shell interpolation, routes, or media forwarding."""
import datetime as dt,ipaddress,json,os,re,socket,subprocess,sys,time
from pathlib import Path
import collection,services,relay,rendering,publication,configuration,identity_defaults
from task_lifecycle import MAINTENANCE
from scheduler import Scheduler,DEFAULT_TIMES
from urllib.parse import urlsplit,urljoin
from iptv_client.client import atomic_text,session_identity
from iptv_client.publisher import playlist,TZ
from iptv_client.collector import collect_data
from iptv_client.platform import PlatformService,catalog_counts
from iptv_client.catalog import catchup_template
from iptv_client.transport import DirectTransport
from iptv_client.network_dns import resolve_entry,select_dns,MissingIPTVDNS

STATE=Path('/var/lib/iptvhelper-app')
PUBLIC=Path('/etc/iptvhelper-data/media')
def cmd(*a):return subprocess.check_output(a,text=True,stderr=subprocess.DEVNULL,timeout=3).strip()
def settings():
    return configuration.defaults(json.loads(cmd('ubus','call','uci','get',json.dumps({'config':'iptvhelper','section':'main'})))['values'])

def effective_settings():
    import policy
    s=settings();snapshot=policy.read_state()
    fresh=snapshot.get('interface')==s.get('interface','iptv') and 0<=time.time()-snapshot.get('time',0)<20
    identity=snapshot.get('identity',{}) if fresh else {}
    net=snapshot.get('network',{}) if fresh else {}
    result=dict(s,stb_id=identity.get('hostname',''),mac=identity.get('mac',''))
    identity_errors=configuration.errors(result)
    ready=bool(fresh and snapshot.get('up') and net.get('up') and net.get('l3_device') and snapshot.get('device')==net.get('l3_device') and not any(k in identity_errors for k in ('stb_id','mac')))
    try:
        address=ipaddress.IPv4Address(net['ipv4-address'][0]['address'])
        if address.is_unspecified or address.is_multicast:ready=False
        routes=net.get('route',[])+net.get('inactive',{}).get('route',[])
        gateway=next(r['nexthop'] for r in routes if r.get('mask')==0)
        ipaddress.IPv4Address(gateway)
        try:ipaddress.IPv4Address(urlsplit(s.get('entry_url','')).hostname)
        except (ValueError,TypeError):select_dns(net,s.get('dns_override',''))
    except (KeyError,IndexError,ValueError,TypeError,StopIteration,MissingIPTVDNS):ready=False
    result['_network_ready']=ready
    return result

def readiness(s):
    if s.get('service_enabled','1')=='0':return 'disabled'
    return 'ready' if s.get('_network_ready') else 'network_unavailable'

def read(path,default=None):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return default
def interface(name):
    import policy
    snapshot=policy.read_state()
    if snapshot.get('interface')!=name or time.time()-snapshot.get('time',0)>20:return {'up':False}
    return snapshot.get('network',{'up':False})

def public_json(path,value):
    atomic_text(path,json.dumps(value,ensure_ascii=False));os.chmod(path,0o644)
def validate_url(value):
    u=urlsplit(value)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('Invalid base URL')
    _=u.port
    return value.rstrip('/')

class IPTVPolicyUnavailable(ConnectionError):pass

def ensure_policy(name,device,apply=False):
    import policy
    state=policy.apply() if apply else policy.read_state()
    if (not state.get('up') or state.get('interface')!=name or state.get('device')!=device
            or time.time()-state.get('time',0)>20):
        raise IPTVPolicyUnavailable('IPTV routing policy is not ready for selected interface')

class PlatformTransport:
    def __init__(self,name,dns_override=''):
        self.name=name
        self.dns_override=dns_override
        st=interface(name)
        if not st.get('up'):raise ConnectionError('IPTV interface is down')
        ensure_policy(name,st.get('l3_device'),apply=False)
        self.source_ip=st['ipv4-address'][0]['address']
    def request(self,method,url,headers=None,body=b''):
        st=interface(self.name)
        if not st.get('up') or st['ipv4-address'][0]['address']!=self.source_ip:raise ConnectionError('IPTV address changed; restart session')
        ensure_policy(self.name,st.get('l3_device'))
        host=urlsplit(url).hostname
        try:target=str(ipaddress.IPv4Address(host))
        except ipaddress.AddressValueError:
            routes=st.get('route',[])+st.get('inactive',{}).get('route',[])
            gw=next(r['nexthop'] for r in routes if r.get('mask')==0)
            target=resolve_entry(host,st,gw,self.dns_override)
        transport=DirectTransport({'device':st['l3_device'],'source_ip':self.source_ip,'connect_ips':{host:target},'timeout':15})
        return transport.request(method,url,headers,body)
    def close(self):pass

def platform_config(s):
    c=json.loads(Path('/usr/share/iptvhelper-app/profile.json').read_text())
    for key in ('entry_url','user_id','password','stb_id','mac'):c[key]=s.get(key,'')
    u=urlsplit(c['entry_url'])
    if u.scheme!='http' or not u.hostname or u.username or u.password:raise ValueError('Invalid platform URL')
    c['trusted_origins']=[u.scheme+'://'+u.netloc]
    c['auth_ip']=None
    return c

def publication_config(s,base):
    c=dict(base)
    for key in ('udpxy_base','rtp2httpd_base','media_base'):c.pop(key,None)
    c['epg_url']='file://'+(PUBLIC/'epg.xml').as_posix()
    c.pop('source_id',None)
    c['epg_database']='/etc/iptvhelper-data/epg.sqlite3'
    return c

def safe_url(value):
    """Never project query strings, userinfo, fragments or servlet session IDs."""
    try:
        u=urlsplit(value or '')
        if u.scheme not in ('http','https','rtsp') or not u.hostname:return ''
        host=u.hostname
        if ':' in host:host='['+host+']'
        return u.scheme+'://'+host+(':'+str(u.port) if u.port else '')+re.sub(r';[^/]*','',u.path)
    except ValueError:return ''

def stamp(value):
    try:return dt.datetime.fromtimestamp(float(value),TZ).isoformat()
    except (TypeError,ValueError,OverflowError):return None

def platform_state(s):
    value=read(STATE/'platform.private.json',{})
    if value.get('identity')!=session_identity(s,''):
        return {'status':'unauthenticated','snapshot':None,'error':None}
    return value

def localize_status(value):
    if isinstance(value,dict):return {k:localize_status(v) for k,v in value.items()}
    if isinstance(value,list):return [localize_status(v) for v in value]
    if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',value):
        return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    return value

def overview():
    # Read the router timezone on each RPC call, including after system changes.
    if hasattr(time,'tzset'):
        try:os.environ['TZ']=Path('/etc/TZ').read_text().strip()
        except OSError:pass
        time.tzset()
    result=_overview();result['checked_at']=dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return localize_status(result)

def _overview():
    s=effective_settings();last=read(STATE/'app-status.json',{})
    try:
        st=interface(s.get('interface','iptv'))
        addr=(st.get('ipv4-address') or [{}])[0]
        routes=st.get('route',[])+st.get('inactive',{}).get('route',[])
        net={'interface':s.get('interface','iptv'),'up':st.get('up',False),'device':st.get('l3_device',''),'address':addr.get('address',''),'mask':addr.get('mask'),
             'gateway':next((r.get('nexthop') for r in routes if r.get('mask')==0),None),'uptime':st.get('uptime'),
             'mac':s.get('mac',''),'hostname':s.get('stb_id',''),'dns_interface':st.get('dns-server',[]),'dns_inactive':st.get('inactive',{}).get('dns-server',[])}
        try:
            dns,source=select_dns(st,s.get('dns_override',''))
            net.update(dns=[dns],dns_source=source)
        except (MissingIPTVDNS,ValueError) as e:
            net.update(dns=[],dns_source='unavailable',dns_error=type(e).__name__)
    except Exception:net={'up':False}
    try:media=relay.running()
    except Exception:media=False
    release=publication.manifest(PUBLIC)
    success=release.get('summary',read(STATE/'last-published.json',read(STATE/'last-success.json',{})))
    session=read(STATE/'session/session.private.json',{})
    login=read(STATE/'session/login-status.private.json',{})
    if login.get('identity')!=session_identity(s,''):login={}
    if not login and session.get('identity')==session_identity(s,net.get('address','')) and session.get('created'):
        login={'status':'authenticated','attempted':session['created']}
    first=platform_state(s);snapshot=first.get('snapshot') or {}
    catalog=snapshot.get('catalog',{})
    discovery=catalog.get('discovery',{})
    discovered=stamp(snapshot.get('at'))
    endpoints=[{'name':label,'url':safe_url(discovery.get(key)),'source':source} for key,label,source in (
        ('entry','认证入口','基本配置'),('portal','EPG 门户','认证返回'),('tvod_landing','回看入口','业务列表'),
        ('catchup_catalog','回看频道目录','页面引用' if discovery.get('catchup_reference_returned') else '地域适配器'))]
    endpoints.append({'name':'频道列表','url':safe_url(session.get('channel_form',{}).get('action')),'source':'认证返回表单'})
    # The regional EPG leaf is adapter knowledge, not a server-discovered endpoint.
    profile=read('/usr/share/iptvhelper-app/profile.json',{})
    endpoints.append({'name':'节目单查询','url':safe_url(urljoin(discovery.get('portal',''),profile.get('adapter',{}).get('epg_path','default/en/datajsp/tvod_IchanListData-hd3.jsp'))),'source':'地域适配器 + 门户地址'})
    coverage=[]
    for day in success.get('dates',[]):
        groups={key:{r['channel'] for r in success.get(key,[]) if r.get('date')==day} for key in ('empty','errors','stale')}
        coverage.append({'date':day,'with_programmes':max(0,success.get('channels',0)-len(set.union(*groups.values()))),
                         'empty':len(groups['empty']),'failed':len(groups['errors']),'stale':len(groups['stale'])})
    if 'coverage' in release:coverage=release['coverage']
    files=[]
    for name,label in [('playlist.m3u','M3U 播放列表'),('epg.xml','XMLTV 节目单')]:
        try:
            info=(PUBLIC/name).stat();exists=True;size=info.st_size;modified=stamp(info.st_mtime)
        except OSError:exists=False;size=0;modified=None
        files.append({'name':label,'path':'/'+name,'exists':exists,'bytes':size,'modified':modified})
    import policy as routing
    route_state=routing.read_state()
    policy=route_state.get('route_entries',[])
    if not policy:policy=[str(x) for x in route_state.get('routes',[])]
    planner=Scheduler(read(SCHEDULE_FILE,{}))
    planner.configure(s,time.time())
    schedule=planner.project(time.time(),s.get('enabled')=='1',stamp)
    return {'readiness':readiness(s),'service_enabled':s.get('service_enabled','1')!='0','configuration_errors':configuration.errors(s,require_platform=True,include_identity=False),'relay':read(STATE/'relay.json',{}),'enabled':s.get('enabled')=='1','network':net,'media_running':media,'last':last,
            'progress':read(STATE/'progress.json',{}),'success':success,'public_path':'/',
            'platform':{'account':s.get('user_id',''),'password_configured':bool(s.get('password')),'entry':safe_url(s.get('entry_url')),'session_cached':bool(session),'created':stamp(session.get('created')),
                        'auth':{'status':login.get('status','unauthenticated'),'checked':stamp(login.get('attempted')),'error':login.get('error')},
                        'verification':{'status':first.get('status','unauthenticated'),'checked':stamp(first.get('checked')),'error':first.get('error'),'has_snapshot':bool(snapshot)},'counts':snapshot.get('counts',{}),
                        'portal':safe_url(discovery.get('portal')),'discovered':discovered,'channels':len(catalog.get('channels',[])),'endpoints':endpoints},
            'services':services.project(read(STATE/'services.json',{}) if s.get('service_enabled','1')!='0' else {}),'collection':collection.project(release.get('collection',read(STATE/'collection.json',{})),last,readiness(s)),'publication':{'coverage':coverage,'files':files},'policy':{'table':route_state.get('table'),'routes':policy},
            'schedule':{'collect_times':s.get('collect_times',DEFAULT_TIMES),'past_days':s.get('past_days','7'),'future_days':s.get('future_days','3'),
                        **schedule},'pending':(STATE/'refresh.request').exists(),
            'media_port':int(s.get('relay_port','5141'))}

def write_if_changed(path,text):
    import tempfile
    encoded=text.encode('utf-8')
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.'+path.name+'.',delete=False) as output:
        temporary=Path(output.name);output.write(encoded);output.flush();os.fsync(output.fileno())
    try:
        if path.exists() and path.read_bytes()==encoded:return False
        os.chmod(temporary,0o644);os.replace(temporary,path);return True
    finally:temporary.unlink(missing_ok=True)

def publish_media(c,summary):
    """Publish database results as local rtp2httpd input files."""
    updated=dt.datetime.now(TZ).isoformat()
    files,counts=rendering.generate(c,summary.get('dates',[]),summary,updated)
    summary=dict(summary,channels=counts['channels'],programmes=counts['programmes'])
    meta=publication.commit(PUBLIC,files,dict(counts,summary=summary),updated)
    # The committed manifest is authoritative. Mirrors are only compatibility aids.
    try:
        atomic_text(STATE/'last-published.json',json.dumps(summary,ensure_ascii=False))
        atomic_text(STATE/'collection.json',json.dumps(meta['collection'],ensure_ascii=False))
    except OSError as error:print('publication mirror: '+type(error).__name__,flush=True)
    return meta

def requested_dates(s,now):
    past=int(s.get('past_days',7));future=int(s.get('future_days',3))
    if not 0<=past<=7 or not 0<=future<=7:raise ValueError('Invalid EPG range')
    return [(now.date()+dt.timedelta(days=n)).strftime('%Y%m%d') for n in range(-past,future+1)]

SCHEDULE_FILE=Path('/etc/iptvhelper-data/schedule.private.json')

def save_schedule(planner):
    SCHEDULE_FILE.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    atomic_text(SCHEDULE_FILE,json.dumps(planner.dump()))
    # Persist the consumed slot before any network request.
    with SCHEDULE_FILE.open('r+b') as stream:os.fsync(stream.fileno())
    if os.name=='posix':
        fd=os.open(str(SCHEDULE_FILE.parent),os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

def once(mode='collect',reason='manual',scheduled=False,lock_fd=None):
    import fcntl
    if mode not in ('collect','export'):raise ValueError('Invalid job')
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (os.fdopen(lock_fd,'a') if lock_fd is not None else (STATE/'app.lock').open('a')) as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'accepted':False,'reason':'already_running'}
        if MAINTENANCE.exists():return {'accepted':False,'reason':'maintenance'}
        s=effective_settings();enabled=s.get('enabled')=='1'
        if s.get('service_enabled','1')=='0':return {'phase':'disabled'}
        if mode=='collect' and readiness(s)!='ready':
            result={'accepted':False,'phase':'network_unavailable','reason':'network_unavailable'}
            return result
        planner=Scheduler(read(SCHEDULE_FILE,{}));planner.configure(s,time.time())
        if scheduled:
            mode=planner.due(time.time(),enabled)
            if mode is None:return {'accepted':False,'reason':'not_due'}
            reason='configuration' if planner.pending else 'scheduled'
        planner.recover()
        planner.started(time.time(),mode,enabled,reason)
        save_schedule(planner)
        atomic_text(STATE/'schedule.json',json.dumps(planner.project(time.time(),enabled,stamp)))
        result={'phase':'failed'}
        try:
            for attempt in range(3):
                if attempt:
                    atomic_text(STATE/'app-status.json',json.dumps(dict(result,phase='running',retry_attempt=attempt+1)))
                    time.sleep((10,30)[attempt-1])
                result=_attempt(mode);result['attempts']=attempt+1
                if result.get('phase') in ('ready','needs_configuration','disabled'):break
            atomic_text(STATE/'app-status.json',json.dumps(result))
            return result
        finally:
            planner.finished(time.time(),mode,result,enabled)
            save_schedule(planner)
            atomic_text(STATE/'schedule.json',json.dumps(planner.project(time.time(),enabled,stamp)))

def _attempt(mode):
    s=settings();now=dt.datetime.now(TZ)
    previous=read(STATE/'app-status.json',{})
    status={'phase':'running','job':mode,'started':now.isoformat(),'previous_phase':previous.get('previous_phase') if previous.get('phase')=='running' else previous.get('phase')}
    atomic_text(STATE/'progress.json',json.dumps({'phase':'export' if mode=='export' else 'discovery'}))
    atomic_text(STATE/'app-status.json',json.dumps(status))
    try:
        s=effective_settings()
        if readiness(s)=='disabled':
            status.update(phase='disabled',finished=dt.datetime.now(TZ).isoformat())
            atomic_text(STATE/'app-status.json',json.dumps(status))
            return status
        s=configuration.validate(s,include_identity=False)
        if mode=='collect' and readiness(s)!='ready':raise IPTVPolicyUnavailable('IPTV network is not ready')
        base=platform_config(s)
        c=publication_config(s,base)
        dates=requested_dates(s,now)
        if mode=='export':
            old=publication.manifest(PUBLIC)
            summary=dict(old.get('summary',{}))
            summary['dates']=dates
        else:
            factory=lambda:PlatformTransport(s.get('interface','iptv'),s.get('dns_override',''))
            with PlatformService(base,STATE,transport_factory=factory) as platform:
                platform.refresh()
                summary=collect_data(c,STATE,dates,platform)
        status.update(channel_status=summary.get('channel_status'),epg_status=summary.get('epg_status'),publication_status='pending')
        meta=publish_media(c,summary)
        status.update(publication_status='ok',phase='ready' if summary.get('success',True) else 'degraded',
                      finished=dt.datetime.now(TZ).isoformat(),channels=meta['channels'],programmes=meta['programmes'],version=meta['version'])
    except IPTVPolicyUnavailable:
        status.update(phase='network_unavailable',finished=dt.datetime.now(TZ).isoformat())
    except configuration.InvalidConfiguration as e:
        status.update(phase='needs_configuration',finished=dt.datetime.now(TZ).isoformat(),configuration_errors=e.errors)
    except Exception as e:
        status.update(phase='failed',finished=dt.datetime.now(TZ).isoformat(),error=type(e).__name__)
        if status.get('publication_status')=='pending':status['publication_status']='failed'
    atomic_text(STATE/'app-status.json',json.dumps(status))
    return status

def request_update():
    if settings().get("service_enabled","1")=="0":return {"accepted":False,"reason":"disabled"}
    import fcntl
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (STATE/'app.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'accepted':False,'reason':'already_running'}
        if MAINTENANCE.exists():return {'accepted':False,'reason':'maintenance'}
        # Pass the already-held flock to the child: no launch race or queue.
        if settings().get('service_enabled','1')=='0':return {'accepted':False,'reason':'disabled'}
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'manual-worker',str(lock.fileno())],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         start_new_session=True,pass_fds=(lock.fileno(),))
    return {'accepted':True}

def recover_execution():
    import fcntl
    with (STATE/'app.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        planner=Scheduler(read(SCHEDULE_FILE,{}))
        if planner.recover():
            save_schedule(planner)
            status=read(STATE/'app-status.json',{})
            if status.get('phase')=='running':
                status['phase']='interrupted'
                atomic_text(STATE/'app-status.json',json.dumps(status))

def daemon():
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    recover_execution()
    services.start(STATE,settings)
    relay.start(settings,interface)
    while True:
        try:
            s=effective_settings();enabled=s.get('enabled')=='1'
            planner=Scheduler(read(SCHEDULE_FILE,{}));planner.configure(s,time.time())
            if planner.due(time.time(),enabled) is not None:
                once(scheduled=True)
            else:
                atomic_text(STATE/'schedule.json',json.dumps(planner.project(time.time(),enabled,stamp)))
        except Exception as error:
            print('scheduler: '+type(error).__name__,flush=True)
        time.sleep(120)

if __name__=='__main__':
    os.umask(0o077)
    action=sys.argv[1] if len(sys.argv)>1 else 'status'
    if action in ('enable','disable'):
        from control import change
        print(json.dumps(change(action=='enable')))
    elif action=='daemon':daemon()
    elif action=='manual-worker':once(lock_fd=int(sys.argv[2]))
    else:print(json.dumps({'status':overview,'update':request_update,'once':once,'export':lambda:once(mode='export')}[action](),ensure_ascii=False))
