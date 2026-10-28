import json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import configuration,lifecycle,policy,relay

class Tests(unittest.TestCase):
    def setUp(self):
        if sys.platform == 'win32':
            fake=type('F',(),{'LOCK_EX':1,'LOCK_NB':2,'flock':staticmethod(lambda *a:None)})
            context=patch.dict(sys.modules,{'fcntl':fake})
            context.start();self.addCleanup(context.stop)
    def valid(self):
        return dict(entry_url='http://example.test:8082/EDS/jsp/AuthenticationURL',
                    user_id='example',password='123456',stb_id='A'*32,
                    mac='02:00:00:00:00:01')
    def test_valid_and_invalid_configuration(self):
        self.assertFalse(configuration.errors(self.valid()))
        for key,value in [('password','secret'),('entry_url','https://example.test'),
                          ('entry_url','http://user:password@example.test'),
                          ('entry_url','http://example.test:0'),('past_days','1.5'),
                          ('future_days','8'),('dns_override','bad'),('interface','eth 3')]:
            with self.subTest(key=key,value=value):
                with self.assertRaises(configuration.InvalidConfiguration) as ctx:
                    configuration.validate(dict(self.valid(),**{key:value}))
                self.assertIn(key,ctx.exception.errors)
                self.assertNotIn(value,str(ctx.exception))
    def test_upgrade_and_reinstall_preserve_configuration(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            base=Path(tmp);config=base/'etc/config/iptvhelper';config.parent.mkdir(parents=True)
            config.write_text('user configuration')
            calls=[]
            def run(args,**kw):
                calls.append(args)
                output='"status":{} "update":{}' if 'list' in args else '{"network":{},"configuration_errors":{}}'
                return subprocess.CompletedProcess(args,0,output,'')
            service=lifecycle.Lifecycle(base,run)
            service.upgrade();config.write_text('factory')
            with patch.object(lifecycle,'check_runtime'):service.install()
            self.assertEqual(config.read_text(),'user configuration')
            self.assertTrue((base/'etc/iptvhelper-data/last-upgrade-config').exists())
            self.assertFalse(any('rtp2httpd' in ' '.join(c) for c in calls))
            policy_restart=[str(base/'etc/init.d/iptvhelper-policy'),'restart']
            policy_running=[str(base/'etc/init.d/iptvhelper-policy'),'running']
            app_restart=[str(base/'etc/init.d/iptvhelper-app'),'restart']
            self.assertLess(calls.index(policy_restart),calls.index(policy_running))
            self.assertLess(calls.index(policy_running),calls.index(app_restart))
            self.assertLess(calls.index(app_restart),calls.index([str(base/'etc/init.d/rpcd'),'reload']))
    def test_rpc_refresh_only_removes_menu_cache(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            temp=Path(tmp)/'tmp';temp.mkdir()
            (temp/'luci-indexcache.test.json').write_text('old')
            (temp/'session').write_text('keep')
            calls=[]
            def run(args,**kw):
                calls.append(args)
                output='"status":{} "update":{}' if 'list' in args else '{"network":{},"configuration_errors":{}}'
                return subprocess.CompletedProcess(args,0,output,'')
            lifecycle.Lifecycle(tmp,run).refresh_rpc()
            self.assertFalse((temp/'luci-indexcache.test.json').exists())
            self.assertTrue((temp/'session').exists())
            self.assertFalse(any(c[-1]=='restart' for c in calls))
    def test_rpc_missing_method_fails(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            def run(args,**kw):return subprocess.CompletedProcess(args,0,'"status":{}','')
            with patch.object(lifecycle.time,'sleep'):
                with self.assertRaises(RuntimeError):lifecycle.Lifecycle(tmp,run).refresh_rpc()
    def test_failed_policy_start_does_not_restart_app(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            calls=[]
            def run(args,**kw):
                calls.append(args)
                return subprocess.CompletedProcess(args,1 if args[-1]=='running' else 0,'','')
            with patch.object(lifecycle,'check_runtime'),patch.object(lifecycle.time,'sleep'):
                with self.assertRaises(RuntimeError):lifecycle.Lifecycle(tmp,run).install()
            self.assertFalse(any(c[0].endswith('/iptvhelper-app') and c[-1]=='restart' for c in calls))
    def test_remove_preserves_data_and_only_stops_owned_relay(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            base=Path(tmp);data=base/'etc/iptvhelper-data';data.mkdir(parents=True)
            (data/'source.sqlite3').write_bytes(b'database')
            calls=[]
            def run(args,**kw):
                calls.append(args)
                return subprocess.CompletedProcess(args,0,json.dumps({'values':{'main':{'.type':'rtp2httpd','upstream_interface':'eth3'}}}),'')
            with patch.object(lifecycle.policy,'read_state',return_value={'device':'eth3'}),patch.object(lifecycle.policy,'remove_owned') as remove:
                lifecycle.Lifecycle(base,run).remove();remove.assert_called_once()
            self.assertEqual((data/'source.sqlite3').read_bytes(),b'database')
            self.assertIn([str(base/'etc/init.d/iptvhelper-relay'),'stop'],calls)
    def test_remove_never_controls_official_relay(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            calls=[]
            def run(args,**kw):
                calls.append(args)
                return subprocess.CompletedProcess(args,0,'','')
            with patch.object(lifecycle.policy,'remove_owned') as remove:
                lifecycle.Lifecycle(tmp,run).remove();remove.assert_called_once()
            self.assertFalse(any(c[0]=='ubus' or c[0].endswith('/rtp2httpd') for c in calls))
    def test_private_relay_arguments_and_collision(self):
        args=relay.plan({},'eth3')
        self.assertIn('0.0.0.0:5141',args)
        self.assertIn('/var/run/iptvhelper-relay.pid',args)
        self.assertIn('--noconfig',args)
        self.assertIn('file:///etc/iptvhelper-data/media/playlist.m3u',args)
        self.assertEqual(args[args.index('--external-m3u-update-interval')+1],'120')
        with self.assertRaises(ValueError):relay.plan({},'eth3; reboot')
        import socket
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            with self.assertRaises(OSError):relay.available({'relay_listen':'127.0.0.1','relay_port':str(listener.getsockname()[1])})
    def test_policy_removal_preserves_foreign_rules_and_guard_order(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            commands=[]
            rules=[{'priority':100,'oif':'eth3','table':'42420','protocol':'242'},
                   {'priority':101,'oif':'eth3','action':'unreachable','protocol':'242'},
                   {'priority':100,'oif':'eth9','table':'42420','protocol':'static'}]
            routes=[{'dst':'default','dev':'eth3','gateway':'192.0.2.1','protocol':'242','metric':10},
                    {'dst':'198.51.100.0/24','dev':'eth9','protocol':'static'}]
            def run(*args):
                if args[:4]==('ip','-j','-4','rule'):return json.dumps(rules)
                if args[:4]==('ip','-j','-4','route'):return json.dumps(routes)
                commands.append(args);return ''
            fake=type('F',(),{'LOCK_EX':1,'flock':staticmethod(lambda *a:None)})
            with patch.dict(sys.modules,{'fcntl':fake}),patch.object(policy,'LOCK',Path(tmp)/'lock'),patch.object(policy,'run',side_effect=run),patch.object(policy,'save'):
                policy.remove_owned()
            self.assertEqual(len(commands),3)
            self.assertIn('100',commands[0]);self.assertIn('route',commands[1]);self.assertIn('101',commands[2])
            self.assertFalse(any('eth9' in cmd or 'main' in cmd or 'flush' in cmd for cmd in commands))

if __name__=='__main__':unittest.main()
