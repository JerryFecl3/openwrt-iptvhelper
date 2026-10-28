import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import app,configuration,policy,collection

class Tests(unittest.TestCase):
    def settings(self):
        return dict(entry_url='http://example.test/entry',user_id='test',password='123456')
    def test_user_validation_excludes_only_derived_identity(self):
        self.assertEqual(configuration.errors(self.settings(),include_identity=False),{})
        self.assertIn('mac',configuration.errors(self.settings()))
        self.assertIn('password',configuration.errors(dict(self.settings(),password=''),include_identity=False))
    def test_snapshot_readiness_and_no_duplicate_fetch(self):
        good={'interface':'iptv','time':100,'up':True,'device':'eth3','identity':{'hostname':'Router-2','mac':'02:00:00:00:00:01'},'network':{'up':True,'l3_device':'eth3','dns-server':['192.0.2.53'],'route':[{'mask':0,'nexthop':'192.0.2.1'}],'ipv4-address':[{'address':'192.0.2.2'}]}}
        for snapshot,expected in ((good,'ready'),({},'network_unavailable'),(dict(good,time=70),'network_unavailable'),(dict(good,interface='other'),'network_unavailable'),(dict(good,up=False),'network_unavailable'),(dict(good,identity={}),'network_unavailable')):
            with self.subTest(snapshot=snapshot),patch.object(app,'settings',return_value=self.settings()),patch.object(policy,'read_state',return_value=snapshot) as read,patch.object(app.time,'time',return_value=101):
                self.assertEqual(app.readiness(app.effective_settings()),expected)
                read.assert_called_once()
    def test_disabled_takes_precedence(self):
        self.assertEqual(app.readiness({'service_enabled':'0','_network_ready':True}),'disabled')
    def test_incomplete_network_is_not_ready(self):
        net={'up':True,'l3_device':'eth3','ipv4-address':[{'address':'192.0.2.2'}],'route':[{'mask':0,'nexthop':'192.0.2.1'}],'dns-server':['192.0.2.53']}
        for change in ({'ipv4-address':[{}]},{'ipv4-address':[{'address':'invalid'}]},{'route':[]},{'dns-server':[]},{'l3_device':'eth4'}):
            snapshot={'interface':'iptv','time':100,'up':True,'device':'eth3','identity':{'hostname':'Router','mac':'02:00:00:00:00:01'},'network':dict(net,**change)}
            with self.subTest(change=change),patch.object(app,'settings',return_value=self.settings()),patch.object(policy,'read_state',return_value=snapshot),patch.object(app.time,'time',return_value=101):
                self.assertEqual(app.readiness(app.effective_settings()),'network_unavailable')
    def test_unready_does_not_consume_schedule(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp);ledger=path/'ledger';ledger.write_text('{"last_slot":"2020-01-01 00:05"}')
            previous=path/'app-status.json';previous.write_text('{"phase":"ready"}')
            fake=type('F',(),{'LOCK_EX':1,'LOCK_NB':2,'flock':staticmethod(lambda *a:None)})
            with patch.dict(sys.modules,{'fcntl':fake}),patch.object(app,'STATE',path),patch.object(app,'SCHEDULE_FILE',ledger),patch.object(app,'effective_settings',return_value=self.settings()),patch.object(app,'_attempt') as attempt:
                self.assertEqual(app.once(scheduled=True)['phase'],'network_unavailable')
                self.assertEqual(ledger.read_text(),'{"last_slot":"2020-01-01 00:05"}')
                self.assertEqual(previous.read_text(),'{"phase":"ready"}')
                attempt.assert_not_called()
                with patch.object(app,'effective_settings',return_value=dict(self.settings(),enabled='1',_network_ready=True)),patch.object(app,'_attempt',return_value={'phase':'ready'}) as resumed:
                    self.assertEqual(app.once(scheduled=True)['phase'],'ready')
                    resumed.assert_called_once()
    def test_network_failure_preserves_counts_not_success_status(self):
        result=collection.project({'updated':'old','live':{'count':150}},{'phase':'network_unavailable'})
        self.assertEqual(result['status'],'network_unavailable')
        self.assertEqual(result['live']['count'],150)
        self.assertEqual(result['updated'],'old')
    def test_attempt_never_authenticates_without_network(self):
        for extra,phase in (({},'network_unavailable'),({'service_enabled':'0'},'disabled')):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
                s=dict(self.settings(),**extra)
                with patch.object(app,'STATE',Path(tmp)),patch.object(app,'settings',return_value=s),patch.object(app,'effective_settings',return_value=s),patch.object(app,'platform_config') as config,patch.object(app,'PlatformService') as platform:
                    result=app._attempt('collect')
                self.assertEqual(result['phase'],phase)
                self.assertNotIn('configuration_errors',result)
                config.assert_not_called();platform.assert_not_called()
