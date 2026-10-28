import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'iptv-client'),str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app')]
from scheduler import Scheduler
from iptv_client.epg_store import Store,read_snapshot
from iptv_client.collector import collect_data
import rendering,publication,app

class Tests(unittest.TestCase):
    def test_legacy_prefix_does_not_trigger_export_after_restart(self):
        settings={'enabled':'1','media_base':'http://old'}
        s=Scheduler();s.configure(settings,100);s.started(100,'collect',True,'manual')
        s.finished(101,'collect',{'phase':'ready'},True)
        restored=Scheduler(s.dump());restored.configure(dict(settings,media_base='http://new'),200)
        self.assertIsNone(restored.pending)
        before=restored.last_slot
        restored.started(200,'export',True,'configuration')
        restored.finished(201,'export',{'publication_status':'ok'},True)
        self.assertEqual(restored.last_slot,before)
    def test_range_auth_interface_changes_collect(self):
        original={'past_days':'7','password':'a','interface':'iptv'}
        for key,value in [('past_days','6'),('password','b'),('interface','other')]:
            s=Scheduler();s.configure(original,0);s.started(0,'collect',False,'manual');s.finished(0,'collect',{'phase':'ready'},False);s.configure(dict(original,**{key:value}),1)
            self.assertEqual(s.due(1,False),'collect')
    def test_database_generation_readonly_and_no_network(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            path=Path(tmp)/'db';db=Store(path);db.bind_source('test')
            db.save_channels({'channels':[{'id':'1','name':'One','groups':[],'live_url':'igmp://232.0.0.1:1234'}]},1)
            db.success('1','20261027',{'programmes':[{'channel_id':'1','id':'p','title':'News','start':'20261027000000','stop':'20261027010000'}]},1);db.close()
            before=path.read_bytes()
            cfg={'epg_database':path,'source_id':'test','epg_url':'epg.xml','udpxy_base':'http://new:5140','rtp2httpd_base':'http://new:5140'}
            with patch('socket.socket',side_effect=AssertionError('network forbidden')):
                files,counts=rendering.generate(cfg,['20261027'],{},'now')
            self.assertIn('udp://232.0.0.1:1234',files['playlist.m3u'])
            self.assertNotIn('http://new:5140',files['playlist.m3u'])
            self.assertEqual(path.read_bytes(),before);publication.validate(files)
            with self.assertRaises(ValueError):read_snapshot(path,'other',['20261027'])
    def test_collector_does_not_publish(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            class Platform:
                catalog={'channels':[{'id':'1','name':'One','groups':[]}]}
                def epg(self,*args):return {'programmes':[]}
            with patch('iptv_client.collector.time.sleep'),patch('iptv_client.publisher.publish',side_effect=AssertionError('must not publish')):
                result=collect_data({},Path(tmp),['20261027'],Platform())
            self.assertTrue(result['success']);self.assertFalse((Path(tmp)/'public').exists())
    def test_export_orchestration_does_not_instantiate_platform(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            with patch.object(app,'SCHEDULE_FILE',Path(tmp)/'schedule.private.json'),patch.object(app,'STATE',Path(tmp)),patch.object(app,'settings',return_value={}),patch.object(app.configuration,'validate',side_effect=lambda s,**kw:s),patch.object(app,'platform_config',return_value={}),patch.object(app,'publication_config',return_value={'source_id':'x'}),patch.object(app,'PlatformService',side_effect=AssertionError('no platform')),patch.object(app,'publish_media',return_value={'channels':1,'programmes':1,'version':'v'}),patch.dict(sys.modules,{'fcntl':type('F',(),{'LOCK_EX':1,'LOCK_NB':2,'flock':staticmethod(lambda *a:None)})}):
                result=app.once(mode='export')
            self.assertEqual(result['publication_status'],'ok')
