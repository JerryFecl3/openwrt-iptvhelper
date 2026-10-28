import sys,json,tempfile,unittest,datetime
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
from scheduler import Scheduler
from iptv_client.epg_store import Store,source_identity
from iptv_client.publisher import collect
import collection

class Tests(unittest.TestCase):
    def test_source_isolation_and_explicit_legacy_adoption(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            db=Store(Path(tmp)/'db');db.success('1','20261027',{'programmes':[1]},1)
            with self.assertRaises(ValueError):db.bind_source('a')
            db.bind_source('a',adopt=True)
            with self.assertRaises(ValueError):db.bind_source('b',adopt=True)
            self.assertEqual(db.get('1','20261027')['epg']['programmes'],[1]);db.close()
            other=Store(Path(tmp)/'other');other.bind_source('b');self.assertIsNone(other.get('1','20261027'));other.close()
        a={'entry_url':'http://a/','user_id':'A','password':'111111'}
        self.assertEqual(source_identity(a),source_identity(dict(a,password='222222')))
        self.assertNotEqual(source_identity(a),source_identity(dict(a,user_id='B')))
    def test_retention_boundaries(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            db=Store(Path(tmp)/'db')
            for d in ('20261017','20261018','20261105','20261106'):db.success('1',d,{'programmes':[]},1)
            self.assertEqual(db.prune('20261027'),2)
            self.assertIsNotNone(db.get('1','20261018'));self.assertIsNotNone(db.get('1','20261105'));db.close()
    def test_global_connection_failure_stops_requests_but_publishes(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            class Platform:
                calls=0
                catalog={'channels':[{'id':str(n),'name':str(n),'groups':[]} for n in range(20)]}
                def epg(self,*a):self.calls+=1;raise ConnectionError()
            p=Platform()
            with patch('iptv_client.publisher.time.sleep'),patch('iptv_client.publisher.publish'):
                r=collect({},Path(tmp),['20261027'],p)
            self.assertEqual(p.calls,1);self.assertFalse(r['success']);self.assertTrue(r['published'])
            self.assertEqual(r['epg_status'],'failed');self.assertEqual(len(r['errors']),20)
    def test_failed_collection_is_not_reported_collected(self):
        self.assertEqual(collection.project({'updated':'now'},{'phase':'degraded','epg_status':'failed'})['status'],'failed')
        self.assertEqual(collection.project({'updated':'now'},{'phase':'degraded','epg_status':'partial'})['status'],'partial')
