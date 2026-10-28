"""Package lifecycle: preserve user data; remove only explicitly owned policy."""
import importlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
import policy
from task_lifecycle import drain,serialized
from iptv_client.client import atomic_text

def check_runtime():
    for name in ('ssl','sqlite3','email.message','http.cookiejar','urllib.request','xml.etree.ElementTree'):
        importlib.import_module(name)
    for name in ('python3','ip','openssl','ubus','uci'):
        if not shutil.which(name):raise RuntimeError('Missing executable: '+name)
    value=subprocess.check_output(['ip','-j','-4','addr','show'],text=True,timeout=5)
    if not isinstance(json.loads(value),list):raise RuntimeError('ip-full JSON support is required')

class Lifecycle:
    def __init__(self,root='/',runner=subprocess.run):self.root=Path(root);self.runner=runner
    def path(self,name):return self.root/name.lstrip('/')
    def run(self,args,check=True):
        result=self.runner(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        if check and result.returncode:raise RuntimeError('Lifecycle command failed: '+args[0])
        return result
    def service(self,name,action,check=True):return self.run([str(self.path('/etc/init.d/'+name)),action],check)
    def enabled(self):
        # Read the restored configuration; an absent option keeps legacy defaults.
        result=self.run(['uci','-c',str(self.path('/etc/config')),'-q','get','iptvhelper.main.service_enabled'],False)
        return result.stdout.strip()!='0'
    def wait_running(self,name):
        # procd registration is asynchronous; successful restart is not readiness.
        for attempt in range(50):
            if self.service(name,'running',False).returncode==0:return
            time.sleep(0.2)
        raise RuntimeError('Service did not start: '+name)
    def refresh_rpc(self):
        # Invalidate generated menus only; never remove session or UCI data.
        for cache in self.path('/tmp').glob('luci-indexcache*'):
            if cache.is_file() and not cache.is_symlink():cache.unlink()
        if self.service('rpcd','running',False).returncode==0:
            self.service('rpcd','reload')
        else:self.service('rpcd','start')
        self.wait_running('rpcd')
        for attempt in range(30):
            result=self.run(['ubus','-t','2','-v','list','iptvhelper'],False)
            if result.returncode==0 and all('"'+method+'"' in result.stdout for method in ('status','update')):
                response=self.run(['ubus','-t','10','call','iptvhelper','status','{}'],False)
                try:status=json.loads(response.stdout)
                except ValueError:status={}
                if response.returncode==0 and isinstance(status,dict) and 'network' in status and 'configuration_errors' in status:return
                raise RuntimeError('IPTV RPC registered but status call failed')
            time.sleep(0.2)
        raise RuntimeError('IPTV RPC registration timed out')
    @serialized
    def install(self):
        check_runtime()
        data=self.path('/etc/iptvhelper-data');data.mkdir(parents=True,exist_ok=True);os.chmod(data,0o700)
        config=self.path('/etc/config/iptvhelper')
        backup=data/'upgrade-config.backup'
        retained=data/'retained-config'
        if backup.exists():
            atomic_text(config,backup.read_text());backup.replace(data/'last-upgrade-config')
        elif retained.exists() and (not config.exists() or "option user_id ''" in config.read_text()):
            atomic_text(config,retained.read_text());retained.replace(data/'last-retained-config')
        if config.exists():os.chmod(config,0o600)
        for path in self.path('/usr/lib/iptvhelper-app').rglob('*.py'):
            os.chmod(path,0o644)
            if hasattr(os,'chown'):os.chown(path,0,0)
        self.path('/var/run/iptvhelper-removing').unlink(missing_ok=True)
        if self.enabled():
            for name in ('iptvhelper-policy','iptvhelper-app'):self.service(name,'enable')
            self.service('iptvhelper-policy','restart')
            self.wait_running('iptvhelper-policy')
            self.service('iptvhelper-app','restart')
            self.wait_running('iptvhelper-app')
        else:
            # Keep both runtime and boot state disabled, including our relay.
            for name in ('iptvhelper-app','iptvhelper-policy','iptvhelper-relay'):
                self.service(name,'stop')
                self.service(name,'disable')
        self.refresh_rpc()
    @serialized
    def upgrade(self):
        # Preserve media and fail-closed rules while replacing helper code.
        self.begin_maintenance()
        with drain(self.root):
            data=self.path('/etc/iptvhelper-data');data.mkdir(parents=True,exist_ok=True);os.chmod(data,0o700)
            config=self.path('/etc/config/iptvhelper')
            if config.exists():atomic_text(self.path('/etc/iptvhelper-data/upgrade-config.backup'),config.read_text())
    def begin_maintenance(self):
        marker=self.path('/var/run/iptvhelper-removing');marker.parent.mkdir(parents=True,exist_ok=True);marker.touch(mode=0o600)
        self.service('iptvhelper-app','stop')
    @serialized
    def remove(self):
        self.begin_maintenance()
        with drain(self.root):self.remove_quiesced()
    def remove_quiesced(self):
        data=self.path('/etc/iptvhelper-data');data.mkdir(parents=True,exist_ok=True);os.chmod(data,0o700)
        config=self.path('/etc/config/iptvhelper')
        if config.exists():atomic_text(self.path('/etc/iptvhelper-data/retained-config'),config.read_text())
        self.service('iptvhelper-policy','stop',False)
        self.service('iptvhelper-relay','stop')
        self.service('iptvhelper-relay','disable',False)
        policy.remove_owned()
        for name in ('iptvhelper-app','iptvhelper-policy'):self.service(name,'disable',False)
        # Configuration, SQLite databases, public artifacts and rtp2httpd package survive.

if __name__=='__main__':
    if os.environ.get('IPKG_INSTROOT'):sys.exit(0)
    try:
        action=sys.argv[1] if len(sys.argv)>1 else 'check'
        if action=='check':check_runtime()
        elif action in ('install','upgrade','remove'):getattr(Lifecycle(),action)()
        else:raise ValueError('Unknown lifecycle action')
    except Exception as error:
        print(str(error),file=sys.stderr);sys.exit(1)
