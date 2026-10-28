import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'iptv-client'))
sys.path.insert(0,str(root/'openwrt-iptv/files/usr/lib/iptvhelper-app'))
spec=importlib.util.spec_from_file_location('app',root/'openwrt-iptv/files/usr/lib/iptvhelper-app/app.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
from iptv_client.publisher import playlist
class Tests(unittest.TestCase):
    def test_first_layer_counts_and_last_success_survive_failure(self):
        from iptv_client.client import Client
        channels=[{'id':'1','groups':['央视','精选'],'live_url':'igmp://232.0.0.1:1234'},
                  {'id':'2','groups':['央视'],'live_url':'igmp://232.0.0.2:1234','timeshift_enabled':True,'catchup_catalog_member':True,'timeshift_url':'rtsp://10.0.0.1/PLTV/test'}]
        self.assertEqual(app.catalog_counts({'channels':channels}),{'groups':2,'live':2,'catchup':1})
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            client=Client.__new__(Client);client.config={};client.state_dir=Path(tmp);client.identity='a';client.state={}
            client._auth_status('authenticated')
            first=json.loads((Path(tmp)/'auth-status.private.json').read_text())['last_success']
            client._auth_status('failed','ProtocolError')
            self.assertEqual(json.loads((Path(tmp)/'auth-status.private.json').read_text())['last_success'],first)
            client.identity='b';client._auth_status('failed','ProtocolError')
            self.assertIsNone(json.loads((Path(tmp)/'auth-status.private.json').read_text())['last_success'])
    def test_platform_state_is_scoped_to_account(self):
        s={'user_id':'x','password':'123456','stb_id':'s','mac':'m','entry_url':'http://portal'}
        observed={'identity':app.session_identity(s,''),'status':'authenticated','snapshot':{'at':123,'counts':{'groups':1,'live':2,'catchup':1}}}
        with patch.object(app,'read',return_value=observed):
            self.assertEqual(app.platform_state(s),observed)
            self.assertEqual(app.platform_state(dict(s,user_id='other'))['status'],'unauthenticated')
            self.assertIsNone(app.platform_state(dict(s,user_id='other'))['snapshot'])
    def test_login_failure_and_success_are_recorded(self):
        from iptv_client.client import Client,ProtocolError
        import time
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            client=Client.__new__(Client);client.config={};client.state_dir=Path(tmp);client.identity='private';client.state={}
            with patch.object(client,'_login',side_effect=ProtocolError('SECRET')):
                with self.assertRaises(ProtocolError):client.login()
            result=json.loads((Path(tmp)/'auth-status.private.json').read_text())
            self.assertEqual(result['status'],'failed');self.assertNotIn('SECRET',json.dumps(result))
            client.state={'created':time.time()}
            with patch.object(client,'_login'):client.login()
            self.assertEqual(json.loads((Path(tmp)/'auth-status.private.json').read_text())['status'],'authenticated')
    def test_dns_selection(self):
        from iptv_client.network_dns import select_dns,MissingIPTVDNS
        st={'dns-server':[],'inactive':{'dns-server':['202.96.64.68']}}
        self.assertEqual(select_dns(st),('202.96.64.68','dhcp_inactive'))
        self.assertEqual(select_dns(st,'192.0.2.53'),('192.0.2.53','manual'))
        self.assertEqual(select_dns({'dns-server':['192.0.2.54'],**{'inactive':st['inactive']}}),('192.0.2.54','interface'))
        with self.assertRaises(MissingIPTVDNS):select_dns({})
        with self.assertRaises(ValueError):select_dns(st,'invalid')
    def test_dns_override_reaches_resolver(self):
        st={'up':True,'l3_device':'eth3','ipv4-address':[{'address':'192.0.2.10'}],'inactive':{'route':[{'mask':0,'nexthop':'192.0.2.1'}]}}
        with patch.object(app,'interface',return_value=st),patch.object(app,'ensure_policy'),patch.object(app,'resolve_entry',return_value='192.0.2.20') as resolver,patch.object(app,'DirectTransport'):
            transport=app.PlatformTransport('iptv','192.0.2.53')
            transport.request('GET','http://portal.example/entry')
            resolver.assert_called_once_with('portal.example',st,'192.0.2.1','192.0.2.53')
    def test_media_both_use_proxy_and_no_account_token(self):
        c={'id':'1','name':'CCTV','groups':['央视'],'live_url':'igmp://232.0.0.27:1234','timeshift_enabled':True,'catchup_catalog_member':True,'timeshift_url':'rtsp://10.1.1.1/PLTV/a?accountinfo=SECRET'}
        text=playlist([c],{'epg_url':'http://lan/iptv/epg.xml','udpxy_base':'http://lan:5140','rtp2httpd_base':'http://lan:5140'})
        self.assertIn('http://lan:5140/udp/232.0.0.27:1234',text)
        self.assertIn('http://lan:5140/rtsp/10.1.1.1/PLTV/',text)
        self.assertNotIn('SECRET',text)
    def test_public_projection_does_not_copy_raw_private_fields(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            state=Path(tmp)/'state';public=Path(tmp)/'public';state.mkdir()
            ch={'id':'1','name':'Example','groups':[],'live_url':'igmp://232.0.0.1:1234','raw':{'password':'SECRET'},'account':'PRIVATE'}
            from iptv_client.epg_store import Store
            db=Store(state/'epg.sqlite3');db.save_channels({'channels':[ch]},1);db.close()
            import rendering
            files,counts=rendering.generate({'epg_database':state/'epg.sqlite3','epg_url':'http://lan/epg.xml','udpxy_base':'http://lan:5140'},[],{},'now')
            text=''.join(files.values())
            self.assertEqual(counts['channels'],1)
            self.assertNotIn('channels.json',files)
            self.assertNotIn('SECRET',text);self.assertNotIn('PRIVATE',text);self.assertNotIn('password',text)
    def test_config_urls_reject_embedded_credentials(self):
        for u in ('file:///etc/passwd','http://root:secret@host/','http://host/?token=secret'):
            with self.assertRaises(ValueError):app.validate_url(u)
    def test_login_record_is_not_changed_by_business_results(self):
        from iptv_client.client import Client,ProtocolError
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            client=Client.__new__(Client);client.config={};client.state_dir=Path(tmp);client.identity='test';client.state={'created':1}
            with patch.object(client,'_login'):client.login()
            path=client.state_dir/'login-status.private.json';before=path.read_bytes()
            client.authenticated(lambda:42)
            self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ProtocolError):client.authenticated(lambda:(_ for _ in ()).throw(ProtocolError('failed')))
            self.assertEqual(path.read_bytes(),before)
            with patch.object(client,'_login',side_effect=ProtocolError('rejected')):
                with self.assertRaises(ProtocolError):client.login()
            self.assertEqual(json.loads(path.read_text())['status'],'failed')
    def test_status_url_redacts_secrets(self):
        self.assertEqual(app.safe_url('http://user:PASS@10.1.2.3:80/EPG/index.jsp;jsessionid=SECRET?token=SECRET#SECRET'),'http://10.1.2.3:80/EPG/index.jsp')
        self.assertEqual(app.safe_url('javascript:alert(1)'),'')
    def test_status_projection_and_coverage(self):
        with tempfile.TemporaryDirectory(dir=root/'openwrt-iptv') as tmp:
            state=Path(tmp);(state/'session').mkdir()
            (state/'session/session.private.json').write_text(json.dumps({'created':1,'identity':'SECRET','channel_form':{'action':'http://host/list?token=SECRET','fields':{'password':'SECRET'}}}))
            (state/'catalog.private.json').write_text(json.dumps({'channels':[{'password':'SECRET'}],'discovery':{'portal':'http://host/EPG/?token=SECRET'}}))
            (state/'last-success.json').write_text(json.dumps({'channels':4,'dates':['20261026'],'empty':[{'channel':'1','date':'20261026'}],'stale':[{'channel':'1','date':'20261026'},{'channel':'2','date':'20261026'}]}))
            with patch.object(app,'STATE',state),patch.object(app,'PUBLIC',state/'public'),patch.object(app,'settings',return_value={'password':'SECRET'}),patch.object(app,'interface',return_value={'up':True}),patch.object(app,'cmd',return_value=''):
                result=app.overview()
            self.assertNotIn('SECRET',json.dumps(result))
            self.assertEqual(result['platform']['auth']['status'],'unauthenticated')
            self.assertEqual(result['publication']['coverage'][0]['with_programmes'],2)
