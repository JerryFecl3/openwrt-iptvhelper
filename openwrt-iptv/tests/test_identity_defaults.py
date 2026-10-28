import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'files/usr/lib/iptvhelper-app'))
import identity_defaults,configuration
from scheduler import fingerprints
class Tests(unittest.TestCase):
    def resolve(self,s,hostname='A'*32,system='Router-2',mac='02:00:00:00:00:01'):
        return identity_defaults.resolve(s,lambda name:{'hostname':hostname},lambda:system,lambda name:mac)
    def test_legacy_overrides_are_ignored(self):
        s={'stb_id':'B'*32,'mac':'02:00:00:00:00:01'}
        result=self.resolve(s)
        self.assertEqual(result['stb_id'],'A'*32)
        self.assertEqual(result['mac'],'02:00:00:00:00:01')
        self.assertEqual(s['stb_id'],'B'*32)
    def test_interface_defaults_without_changing_input(self):
        raw={'interface':'iptv','stb_id':'','mac':''};effective=self.resolve(raw)
        self.assertEqual(effective['stb_id'],'A'*32)
        self.assertEqual(effective['mac'],'02:00:00:00:00:01')
        self.assertEqual(raw['mac'],'')
    def test_system_fallback_and_no_padding(self):
        for hostname in ('','*'):
            effective=self.resolve({},hostname=hostname)
            self.assertEqual(effective['stb_id'],'Router-2')
            self.assertNotIn('stb_id',configuration.errors(effective))
    def test_missing_mac_is_not_invented(self):
        self.assertIn('mac',configuration.errors(self.resolve({},mac='')))
    def test_selected_interface_is_used(self):
        names=[]
        def interface(name):names.append(name);return {'hostname':'C'*32}
        def mac(name):names.append(name);return '02:00:00:00:00:02'
        identity_defaults.resolve({'interface':'iptv2'},interface,lambda:'unused',mac)
        self.assertEqual(names,['iptv2','iptv2'])
    def test_default_changes_invalidate_platform_schedule(self):
        self.assertNotEqual(fingerprints(self.resolve({}))['platform'],fingerprints(self.resolve({},mac='02:00:00:00:00:02'))['platform'])
