import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'iptv-client'))
from iptv_client.platform import PlatformService
from iptv_client.client import ProtocolError,SessionExpired
from iptv_client.publisher import collect

CATALOG={'channels':[{'id':'1','name':'Example','groups':['A'],'live_url':'igmp://232.0.0.1:1234'}]}
class StubClient:
    def __init__(self,*args,**kwargs):self.logins=0
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def login(self):self.logins+=1
    def epg(self,*args):return {'channel_id':'1','programmes':[]}

class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=root/'openwrt-iptv')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.service=PlatformService({},self.path,client_factory=StubClient,catalog_loader=lambda c:CATALOG)
    def saved(self):return json.loads((self.path/'platform.private.json').read_text(encoding='utf-8'))
    def test_snapshot_all_four_values_commit_only_on_first_layer_success(self):
        self.service.refresh();first=self.saved()
        self.assertEqual(first['snapshot']['counts'],{'groups':1,'live':1,'catchup':0})
        self.service.catalog_loader=lambda c:(_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(TimeoutError):self.service.refresh()
        failed=self.saved();self.assertEqual(failed['status'],'unreachable')
        self.assertEqual(failed['snapshot'],first['snapshot'])
        self.service.catalog_loader=lambda c:(_ for _ in ()).throw(ProtocolError('rejected'))
        with self.assertRaises(ProtocolError):self.service.refresh()
        self.assertEqual(self.saved()['status'],'failed')
        self.assertEqual(self.saved()['snapshot'],first['snapshot'])
    def test_never_success_has_no_snapshot(self):
        self.service.catalog_loader=lambda c:(_ for _ in ()).throw(ProtocolError('rejected'))
        with self.assertRaises(ProtocolError):self.service.refresh()
        self.assertIsNone(self.saved()['snapshot'])
    def test_ordinary_epg_failure_and_success_do_not_touch_first_layer(self):
        self.service.refresh();before=(self.path/'platform.private.json').read_bytes()
        for exc in (TimeoutError(),ValueError('invalid EPG'),ProtocolError('HTTP error')):
            with patch.object(self.service.client,'epg',side_effect=exc):
                with self.assertRaises(type(exc)):self.service.epg('1','20261026')
            self.assertEqual((self.path/'platform.private.json').read_bytes(),before)
        self.service.epg('1','20261026')
        self.assertEqual((self.path/'platform.private.json').read_bytes(),before)
    def test_layer_two_collection_failure_preserves_first_layer(self):
        self.service.refresh();before=(self.path/'platform.private.json').read_bytes()
        with patch.object(self.service.client,'epg',side_effect=TimeoutError()),patch('iptv_client.publisher.time.sleep'),patch('iptv_client.publisher.publish'):
            summary=collect({},self.path,['20261026'],self.service)
        self.assertFalse(summary['success']);self.assertTrue(summary['published'])
        self.assertFalse(summary['epg_published'])
        self.assertEqual(len(summary['errors']),1)
        self.assertEqual((self.path/'platform.private.json').read_bytes(),before)
    def test_explicit_expiry_reenters_first_layer_and_refreshes_whole_snapshot(self):
        self.service.refresh()
        with patch.object(self.service.client,'epg',side_effect=[SessionExpired(),{'programmes':[]}]),patch.object(self.service,'catalog_loader',return_value=CATALOG) as loader:
            self.service.epg('1','20261026');loader.assert_called_once()
        self.assertEqual(self.service.client.logins,1)
        self.assertEqual(self.saved()['status'],'authenticated')
    def test_transport_failure_before_client_creation_is_unreachable(self):
        self.service.transport_factory=lambda:(_ for _ in ()).throw(ConnectionError())
        with self.assertRaises(ConnectionError):self.service.refresh()
        self.assertEqual(self.saved()['status'],'unreachable')
