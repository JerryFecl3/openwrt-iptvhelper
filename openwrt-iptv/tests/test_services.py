import sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'iptv-client'))
sys.path.insert(0,str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app'))
import services
class Tests(unittest.TestCase):
    def test_startup_failure_retries_and_returns_to_low_frequency(self):
        self.assertEqual(services.refresh_interval(None),15)
        self.assertEqual(services.refresh_interval({'items':{}}),15)
        result={'items':{k:{'ok':True} for k in services.KEYS}}
        result['items']['relay']['ok']=False
        self.assertEqual(services.refresh_interval(result),15)
        result['items']['relay']['ok']=True
        self.assertEqual(services.refresh_interval(result),300)

    def test_health_validation_and_expiry(self):
        bodies={'http://127.0.0.1:5141/playlist.m3u':b'#EXTM3U\n#EXTINF:1,A\nhttp://a',
                'http://127.0.0.1:5141/epg.xml':b'<tv><channel/><programme/></tv>',
                'http://127.0.0.1:5141/player':b'<html>Player</html>',
                'http://127.0.0.1:5141/status':b'<html>Status</html>'}
        config={'public_base':'http://router','media_base':'http://media'}
        good=services.check(config,bodies.__getitem__)
        self.assertTrue(services.project(good,good['checked'])['ok'])
        self.assertFalse(services.project(good,good['checked']+661)['ok'])
        for url,key in [('http://127.0.0.1:5141/epg.xml','epg'),('http://127.0.0.1:5141/playlist.m3u','m3u'),('http://127.0.0.1:5141/player','player'),('http://127.0.0.1:5141/status','relay')]:
            bad=dict(bodies);bad[url]=b'error'
            result=services.check(config,bad.__getitem__)
            self.assertFalse(result['items'][key]['ok'])
            self.assertFalse(services.project(result,result['checked'])['ok'])
        self.assertFalse(services.project({})['ok'])

    def test_probe_uses_listener_not_public_reverse_proxy(self):
        self.assertEqual(services.local_origin({'media_base':'https://unreachable.example'}),'http://127.0.0.1:5141')
        self.assertEqual(services.local_origin({'relay_listen':'192.0.2.2','relay_port':'5142'}),'http://192.0.2.2:5142')
        calls=[]
        services.check({'media_base':'https://unreachable.example'},lambda url:calls.append(url) or b'error')
        self.assertEqual(len(calls),4)
        self.assertTrue(all(url.startswith('http://127.0.0.1:5141/') for url in calls))
