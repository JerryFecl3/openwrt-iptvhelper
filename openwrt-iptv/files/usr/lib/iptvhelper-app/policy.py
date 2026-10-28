#!/usr/bin/python3
"""IPTV assistant routing owner. Reads iptvhelper.main.interface; never writes main."""
import ipaddress,json,os,re,subprocess,sys,time
from pathlib import Path

TABLE='42420'
PROTO='242'
STATE=Path('/var/run/iptvhelper-policy.json')
LOCK=Path('/var/run/iptvhelper-policy.lock')

def run(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL,timeout=5).strip()

def read_state():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {}

def save(state):
    tmp=STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state));os.chmod(tmp,0o600);os.replace(tmp,STATE)

def selected_interface():
    try:name=run('uci','-q','get','iptvhelper.main.interface') or 'iptv'
    except subprocess.CalledProcessError:name='iptv'
    if not re.fullmatch(r'[A-Za-z0-9_]+',name):raise ValueError('Invalid IPTV logical interface')
    return name

def desired(st):
    dev=st.get('l3_device') or st.get('device')
    if not st.get('up') or not st.get('ipv4-address'):return dev,[]
    if not dev or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,15}',dev):raise ValueError('Invalid IPTV device')
    addr=st['ipv4-address'][0]
    network=ipaddress.IPv4Network(str(addr['address'])+'/'+str(addr['mask']),strict=False)
    routes=st.get('route',[])+st.get('inactive',{}).get('route',[])
    gw=next((r.get('nexthop') for r in routes if r.get('mask')==0 and r.get('nexthop')),None)
    if not gw:return dev,[]
    gateway=ipaddress.IPv4Address(gw)
    if gateway not in network:raise ValueError('IPTV gateway outside connected subnet')
    return dev,[(str(network),None),('default',str(gateway))]

def rule_owned(r,previous):
    priority=r.get('priority');dev=r.get('oif')
    shape=bool(dev) and ((priority==100 and str(r.get('table')) in (TABLE,str(previous.get('table')))) or
                        (priority==101 and r.get('action')=='unreachable'))
    if not shape:return False
    # Adopt only the exact legacy service shape, backed by its runtime state.
    return str(r.get('protocol'))==PROTO or (str(previous.get('table'))==TABLE and
            dev in set(previous.get('guarded_devices',[])+[previous.get('device')]) and r.get('protocol') in (None,'boot',3))

def route_delete(r):
    args=['ip','-4','route','del','table',TABLE]
    if r.get('type')=='unreachable':args.append('unreachable')
    args.extend([r['dst'],'proto',PROTO])
    if r.get('dev'):args.extend(['dev',r['dev']])
    if 'metric' in r:args.extend(['metric',str(r['metric'])])
    run(*args)

def reconcile():
    global TABLE
    previous=read_state()
    try:value=run('uci','-q','get','iptvhelper.main.route_table')
    except subprocess.CalledProcessError:value='42420'
    value=value or '42420'
    if not value.isdigit() or not 1<=int(value)<=4294967295 or int(value) in (253,254,255):raise ValueError('Invalid IPTV routing table')
    TABLE=str(int(value))
    rules=json.loads(run('ip','-j','-4','rule','show'))
    owned=[]
    for r in rules:
        if r.get('priority') not in (100,101):continue
        if not rule_owned(r,previous):raise RuntimeError('Conflicting IPTV policy priority')
        owned.append(r)
    try:routes=json.loads(run('ip','-j','-4','route','show','table',TABLE))
    except subprocess.CalledProcessError as exc:
        # A fresh boot has no FIB table until its first route is installed.
        if exc.returncode!=2:raise
        routes=[]
    if any(str(r.get('protocol'))!=PROTO for r in routes):raise RuntimeError('Foreign route in IPTV table')
    name=None;device=None;wanted=[];error=None;st={};identity={}
    try:
        name=selected_interface()
        st=json.loads(run('ubus','call','network.interface.'+name,'status'))
        device,wanted=desired(st)
        cfg=json.loads(run('ubus','call','uci','get',json.dumps({'config':'network','section':name})))['values']
        hostname=cfg.get('hostname','')
        if not hostname or hostname=='*':
            values=json.loads(run('ubus','call','uci','get','{"config":"system"}'))['values']
            hostname=next((v.get('hostname','') for v in values.values() if v.get('.type')=='system'),'')
        mac=json.loads(run('ubus','call','network.device','status',json.dumps({'name':device}))).get('macaddr','') if device else ''
        identity={'hostname':hostname,'mac':mac.upper()}

        main=json.loads(run('ip','-j','-4','route','show','table','main'))
        if device and any(r.get('dst')=='default' and r.get('dev')==device for r in main):
            raise ValueError('Selected IPTV device carries main default route')
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
        device=None;wanted=[]
    # Install reject fallback first. Old device guards remain to stop old media
    # consumers falling through to main after a configuration switch.
    if not any(r.get('type')=='unreachable' and r.get('dst')=='default' and r.get('metric')==42760 for r in routes):
        run('ip','-4','route','replace','unreachable','default','table',TABLE,'metric','42760','proto',PROTO)
    guards={r['oif'] for r in owned if r.get('priority')==101}
    needed={r['oif'] for r in owned if r.get('priority')==100}
    if device:needed.add(device)
    for dev in sorted(needed-guards):
        run('ip','-4','rule','add','pref','101','oif',dev,'unreachable','protocol',PROTO)
    for r in owned:
        if r.get('priority')==100 and (r['oif']!=device or not wanted or str(r.get('table'))!=TABLE):
            run('ip','-4','rule','del','pref','100','oif',r['oif'],'lookup',str(r['table']))
    for r in routes:
        if r.get('type')=='unreachable':continue
        if r.get('dev')!=device or r.get('metric')!=10 or (r.get('dst'),r.get('gateway')) not in wanted:
            route_delete(r)
    for dst,gw in wanted:
        if any(r.get('dst')==dst and r.get('gateway')==gw and r.get('dev')==device and r.get('metric')==10 for r in routes):continue
        args=['ip','-4','route','replace','table',TABLE,dst,'dev',device,'proto',PROTO,'metric','10']
        args+=['via',gw] if gw else ['scope','link']
        run(*args)
    if wanted and not any(r.get('priority')==100 and r['oif']==device and str(r.get('table'))==TABLE for r in owned):
        run('ip','-4','rule','add','pref','100','oif',device,'lookup',TABLE,'protocol',PROTO)
    result={'time':time.time(),'interface':name,'device':device,'table':TABLE,'up':bool(wanted),
            'network':st,'identity':identity,'routes':wanted,'guarded_devices':sorted(guards|needed),'error':error}
    result['route_entries']=run('ip','-4','route','show','table',TABLE).splitlines()
    save(result)
    old_table=str(previous.get('table',''))
    if old_table.isdigit() and old_table!=TABLE and int(old_table) not in (0,253,254,255):
        # Only our marked routes; never flush another owner's table.
        run('ip','-4','route','flush','table',old_table,'proto',PROTO)
    return result

def apply():
    try:
        if run("uci","-q","get","iptvhelper.main.service_enabled")=="0":return dict(read_state(),up=False)
    except subprocess.CalledProcessError:pass
    import fcntl
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if Path('/var/run/iptvhelper-removing').exists():return dict(read_state(),up=False,error='uninstalling')
        try:return reconcile()
        except Exception as exc:
            state=read_state();state.update(time=time.time(),up=False,error=type(exc).__name__+': '+str(exc));save(state)
            raise

def remove_owned():
    import fcntl
    global TABLE
    previous=read_state()
    TABLE=str(previous.get('table',TABLE))
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rules=json.loads(run('ip','-j','-4','rule','show'))
        try:routes=json.loads(run('ip','-j','-4','route','show','table',TABLE))
        except subprocess.CalledProcessError as error:
            if error.returncode!=2:raise
            routes=[]
        owned=[r for r in rules if str(r.get('protocol'))==PROTO and rule_owned(r,{})]
        # Keep unreachable guards until owned lookup rules and routes are gone.
        for priority in (100,101):
            if priority==101:
                for route in routes:
                    if str(route.get('protocol'))==PROTO:route_delete(route)
            for rule in owned:
                if rule['priority']!=priority:continue
                args=['ip','-4','rule','del','pref',str(priority),'oif',rule['oif']]
                args+=['lookup',TABLE] if priority==100 else ['unreachable']
                run(*args,'protocol',PROTO)
        save({'time':time.time(),'up':False,'table':TABLE,'guarded_devices':[],'removed':True})

if __name__=='__main__':
    if '--remove' in sys.argv:
        remove_owned()
    elif '--watch' not in sys.argv:
        apply()
    else:
        last_error=None
        while True:
            try:
                result=apply();error=result.get('error')
            except Exception as exc:error=str(exc)
            if error and error!=last_error:print(error,file=sys.stderr,flush=True)
            last_error=error
            time.sleep(3)
