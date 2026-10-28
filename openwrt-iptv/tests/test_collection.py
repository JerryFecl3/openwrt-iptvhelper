import sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'iptv-client'))
sys.path.insert(0,str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app'))
import collection

class Tests(unittest.TestCase):
    def test_recovery_clears_only_transient_network_status(self):
        snapshot={'updated':'previous','live':{'count':150}}
        skipped={'phase':'network_unavailable','accepted':False}
        self.assertEqual(collection.project(snapshot,skipped,'network_unavailable')['status'],'network_unavailable')
        recovered=collection.project(snapshot,skipped,'ready')
        self.assertEqual(recovered['status'],'collected')
        self.assertEqual(recovered['updated'],'previous')
        self.assertEqual(recovered['live']['count'],150)
        self.assertEqual(collection.project({},skipped,'ready')['status'],'empty')
        self.assertEqual(collection.project(snapshot,{'phase':'network_unavailable'},'ready')['status'],'failed')
        self.assertEqual(collection.project(snapshot,{'phase':'failed'},'ready')['status'],'failed')
    def test_independent_changes_and_metadata(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as d:
            p=Path(d)
            m='#EXTM3U\n#EXTINF:-1 tvg-id="1" catchup="default" catchup-source="http://a/replay",One\nhttp://a/live\n'
            x='<tv generator-info-name="test"><channel id="1"><display-name>One</display-name></channel><programme channel="1" start="20261026120000 +0800" stop="20261026130000 +0800"><title>News</title></programme></tv>'
            (p/'playlist.m3u').write_text(m)
            (p/'epg.xml').write_text(x)
            first=collection.record(p,p,'t1')
            self.assertEqual([first[k]['count'] for k in ('live','catchup','epg')],[1,1,1])
            (p/'epg.xml').write_text(x.replace('test','new-generator'))
            second=collection.record(p,p,'t2')
            self.assertEqual(second['updated'],'t2')
            self.assertTrue(all(second[k]['changed']=='t1' for k in ('live','catchup','epg')))
            (p/'playlist.m3u').write_text(m.replace('/replay','/replay2'))
            third=collection.record(p,p,'t3')
            self.assertEqual(third['catchup']['changed'],'t3')
            self.assertEqual(third['live']['changed'],'t1')
            (p/'epg.xml').write_text(x.replace('News','News2'))
            fourth=collection.record(p,p,'t4')
            self.assertEqual(fourth['epg']['changed'],'t4')
            self.assertEqual(fourth['catchup']['changed'],'t3')

    def test_states_and_failed_snapshot(self):
        self.assertEqual(collection.project({}, {})['status'],'empty')
        self.assertEqual(collection.project({}, {'phase':'failed'})['status'],'failed')
        snapshot={'updated':'t1','live':{'count':2,'changed':'t0'}}
        for phase in ('failed','degraded'):
            result=collection.project(snapshot,{'phase':phase})
            self.assertEqual(result['status'],'failed' if phase=='failed' else 'partial')
            self.assertEqual(result['updated'],'t1')
            self.assertEqual(result['live']['count'],2)
        self.assertEqual(collection.project(snapshot,{'phase':'running','previous_phase':'failed'})['status'],'failed')
        self.assertEqual(collection.project(snapshot,{'phase':'ready'})['status'],'collected')

