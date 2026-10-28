import unittest,tempfile,json,sys,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iptv_client.catalog import catchup_template
from iptv_client.publisher import playlist,publish
class PublisherTests(unittest.TestCase):
 def channel(self):
  return {'id':'1','name':'Example','number':'1','groups':['A','B'],'logo':'','live_url':'igmp://232.0.0.27:1234','timeshift_enabled':True,'catchup_catalog_member':True,'timeshift_url':'rtsp://10.15.250.13/PLTV/path.smil?rrsip=10.15.250.13&accountinfo=PRIVATE'}
 def test_playlist_catchup_and_no_portal_secret(self):
  text=playlist([self.channel()],{'epg_url':'http://lan/epg.xml','udpxy_base':'http://lan:9999'})
  self.assertIn('http://lan:9999/udp/232.0.0.27:1234',text)
  self.assertIn('group-title="A;B"',text)
  self.assertIn('playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}',text)
  self.assertIn('catchup-correction="0"',text)
  self.assertNotIn('PRIVATE',text)
  self.assertNotIn('accountinfo',text)
 def test_not_in_catchup_catalog_not_advertised(self):
  c=self.channel();c['catchup_catalog_member']=False
  self.assertIsNone(catchup_template(c))
 def test_template_time_for_china_client(self):
  # Kodi formats in client local time; with Asia/Shanghai, no additional shift.
  value=datetime.datetime(2026,10,25,0,0,tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
  t=value.timestamp()
  self.assertEqual(datetime.datetime.fromtimestamp(t,value.tzinfo).strftime('%Y%m%d%H%M%S'),'20261025000000')
 def test_failed_epg_does_not_block_playlist(self):
  from unittest.mock import patch
  from iptv_client.publisher import update
  class Broken:
   def __init__(self,*a):pass
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def epg(self,*a):raise TimeoutError()
  with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
   p=Path(tmp)/'public';p.mkdir();(p/'existing.xml').write_text('last-good')
   with patch('iptv_client.publisher.Client',Broken), patch('iptv_client.publisher.business_catalog',return_value={'channels':[self.channel()]}), patch('iptv_client.publisher.time.sleep'), patch('iptv_client.publisher.publish') as publishing:
    result=update({},tmp,['20261026'])
    self.assertFalse(result['success']);self.assertTrue(result['published']);self.assertFalse(result['epg_published']);self.assertEqual(len(result['errors']),1)
    publishing.assert_called_once()
    self.assertEqual((p/'existing.xml').read_text(),'last-good')
if __name__=='__main__':unittest.main()



