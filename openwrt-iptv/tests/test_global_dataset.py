import sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
import app
from iptv_client.epg_store import Store,read_snapshot
class GlobalDatasetTests(unittest.TestCase):
    def test_config_identity_does_not_change_database(self):
        s={'media_base':'http://router:5141'}
        a=app.publication_config(s,{'user_id':'a','stb_id':'a','mac':'a'})
        b=app.publication_config(s,{'user_id':'b','stb_id':'b','mac':'b','entry_url':'http://other'})
        self.assertEqual(a['epg_database'],b['epg_database'])
        self.assertNotIn('source_id',a)
    def test_channel_replace_preserves_epg_but_filters_exports(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp)/'epg.sqlite3';s=Store(path)
            s.save_channels({'channels':[{'id':'1','name':'Old'}]},1)
            s.success('1','20261027',{'programmes':[{'title':'Old show'}]},1)
            with self.assertRaises(ValueError):s.save_channels({'channels':[]},2)
            self.assertEqual(s.channels()[0]['id'],'1')
            s.save_channels({'channels':[{'id':'2','name':'New'}]},3)
            self.assertIsNotNone(s.get('1','20261027'));s.close()
            channels,entries=read_snapshot(path,None,['20261027'])
            self.assertEqual([c['id'] for c in channels],['2']);self.assertEqual(entries,{})
