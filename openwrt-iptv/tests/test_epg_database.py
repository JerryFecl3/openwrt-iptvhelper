import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'iptv-client'))
sys.path.insert(0,str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app'))
from iptv_client.epg_store import Store,fresh,ordered_dates
from iptv_client.publisher import collect
import app

class Tests(unittest.TestCase):
    def test_order_and_exact_thresholds(self):
        self.assertEqual(ordered_dates(['20261025','20261028','20261026','20261024','20261027'],'20261026'),['20261026','20261027','20261028','20261025','20261024'])
        self.assertFalse(fresh(100,'20261026','20261026',100))
        for day,ttl in [('20261025',43200),('20261027',43200),('20261024',86400),('20261028',86400)]:
            self.assertTrue(fresh(100,day,'20261026',100+ttl-1))
            self.assertFalse(fresh(100,day,'20261026',100+ttl))
    def test_empty_and_nonempty_updates(self):
        with tempfile.TemporaryDirectory(dir=root/"openwrt-iptv") as tmp:
            db=Store(Path(tmp)/'epg.db');empty={'channel_id':'1','programmes':[]};full={'channel_id':'1','programmes':[{'title':'A'}]}
            db.success('1','20261026',empty,100);self.assertEqual(db.get('1','20261026')['fetched_at'],100)
            db.success('1','20261026',full,200);db.success('1','20261026',empty,300)
            self.assertEqual(db.get('1','20261026'),{'fetched_at':300,'epg':full})
            db.close();db=Store(Path(tmp)/'epg.db');self.assertEqual(db.get('1','20261026')['epg'],full);db.close()
    def test_identical_export_preserves_mtime(self):
        with tempfile.TemporaryDirectory(dir=root/"openwrt-iptv") as tmp:
            path=Path(tmp)/'epg.xml'
            self.assertTrue(app.write_if_changed(path,'<tv/>'))
            before=path.stat().st_mtime_ns
            self.assertFalse(app.write_if_changed(path,'<tv/>'));self.assertEqual(before,path.stat().st_mtime_ns)
            self.assertTrue(app.write_if_changed(path,'<tv></tv>'));self.assertEqual(path.read_text(),'<tv></tv>')
    def test_migration_is_once_and_preserves_source(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            folder=Path(tmp)/'old';folder.mkdir()
            source=folder/'1-20261026.json';source.write_text(json.dumps({'fetched_at':100,'epg':{'channel_id':'1','programmes':[]}}))
            db=Store(Path(tmp)/'db');db.migrate(folder)
            self.assertTrue(source.exists());self.assertEqual(db.get('1','20261026')['fetched_at'],100)
            db.success('1','20261026',{'channel_id':'1','programmes':[]},200)
            db.migrate(folder);self.assertEqual(db.get('1','20261026')['fetched_at'],200);db.close()
    def test_unexpired_empty_record_is_skipped_without_write(self):
        import datetime,time
        from iptv_client.publisher import TZ
        day=(datetime.datetime.now(TZ)+datetime.timedelta(days=1)).strftime('%Y%m%d')
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            state=Path(tmp);db=Store(state/'epg.sqlite3');checked=time.time()
            db.success('1',day,{'channel_id':'1','programmes':[]},checked);db.close()
            class Platform:
                catalog={'channels':[{'id':'1','name':'One','groups':[]}]}
                def epg(self,*args):raise AssertionError('must skip')
            with patch('iptv_client.publisher.publish'):
                result=collect({},state,[day],Platform())
            self.assertEqual(result['cached'],1)
            db=Store(state/'epg.sqlite3');self.assertEqual(db.get('1',day)['fetched_at'],checked);db.close()
    def test_failure_does_not_stop_database_export(self):
        with tempfile.TemporaryDirectory(dir=root/"openwrt-iptv") as tmp:
            state=Path(tmp);db=Store(state/'epg.sqlite3')
            programme={'channel_id':'1','id':'1','title':'A','start':'20261026000000','stop':'20261026010000'}
            db.success('1','20261026',{'channel_id':'1','programmes':[programme]},1);db.close()
            class Platform:
                catalog={'channels':[{'id':'1','name':'One','groups':[],'live_url':'igmp://232.0.0.1:1234'},{'id':'2','name':'Two','groups':[],'live_url':'igmp://232.0.0.2:1234'}]}
                def epg(self,*args):raise TimeoutError()
            with patch('iptv_client.publisher.time.sleep'),patch('iptv_client.publisher.publish') as publish:
                result=collect({'epg_url':'epg.xml','udpxy_base':'http://lan:5140'},state,['20261026'],Platform())
            publish.assert_called_once()
            self.assertFalse(result['success']);self.assertTrue(result['published']);self.assertEqual(len(result['errors']),1)
            db=Store(state/'epg.sqlite3');self.assertEqual(db.get('1','20261026')['fetched_at'],1);self.assertIsNone(db.get('2','20261026'));db.close()


    def test_channel_snapshot_transaction_and_fallback(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            db=Store(Path(tmp)/'db')
            db.save_channels({'channels':[{'id':'1','name':'Old','groups':['A'],'catchup_catalog_member':True},{'id':'2','name':'Old'}]},1)
            db.save_channels({'channels':[{'id':'1','name':'New','groups':[],'live_url':'new'},{'id':'3','name':'New','groups':[]}], 'enrichment':{'groups':False,'catchup':False}},2)
            rows=db.channels()
            self.assertEqual([c['id'] for c in rows],['1','3'])
            self.assertEqual(rows[0]['groups'],['A']);self.assertTrue(rows[0]['catchup_catalog_member'])
            self.assertEqual(rows[0]['live_url'],'new')
            with self.assertRaises(ValueError):db.save_channels({'channels':[]},3)
            self.assertEqual(db.channels(),rows)
            db.close();db=Store(Path(tmp)/'db');self.assertEqual(db.channels(),rows);db.close()

    def test_empty_epg_still_publishes_database_channels(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            class Platform:
                catalog={'channels':[{'id':'1','name':'One','groups':[],'live_url':'igmp://232.0.0.1:1234'}]}
                def epg(self,*args):return {'channel_id':'1','programmes':[]}
            with patch('iptv_client.publisher.time.sleep'),patch('iptv_client.publisher.publish') as publish:
                result=collect({},Path(tmp),['20261026'],Platform())
            self.assertTrue(result['success']);self.assertFalse(result['epg_published'])
            self.assertEqual(publish.call_args.args[1][0]['id'],'1')

    def test_auxiliary_failures_keep_base_catalog(self):
        from iptv_client.catalog import business_catalog
        class Client:
            state={'epg_base':'http://test/'};config={'entry_url':'http://test/'}
            def channels(self):return [{'id':'1','name':'One'}]
            def services(self):raise TimeoutError()
            def request(self,*args):raise TimeoutError()
        result=business_catalog(Client())
        self.assertEqual(len(result['channels']),1)
        self.assertEqual(len(result['warnings']),2)
        self.assertEqual(result['enrichment'],{'catchup':False,'groups':False})

    def test_collection_status_without_first_xml(self):
        import collection
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp);(path/'playlist.m3u').write_text('#EXTM3U\n#EXTINF:-1 tvg-id="1",One\nhttp://lan/udp/a\n')
            snapshot=collection.record(path,path,'now')
            self.assertEqual(snapshot['live']['count'],1)
            self.assertEqual(snapshot['epg']['count'],0)
