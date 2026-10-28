import sys,unittest,tempfile,json
from pathlib import Path
from urllib.parse import parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from iptv_client.client import Client,ProtocolError,PurchaseRequired,SessionExpired
from iptv_client.transport import Response
from iptv_client.auth import authenticator

BASE='http://portal.test:33200'
CONFIG={'entry_url':'http://eds.test:8082/start','trusted_origins':['http://eds.test:8082',BASE],
        'user_id':'testuser','password':'123456','stb_id':'S'*32,'mac':'00:11:22:33:44:55','device_fields':{'SupportHD':'1'}}
class Fake:
    source_ip='192.0.2.33'
    def __init__(self,replies):self.replies=list(replies);self.calls=[]
    def request(self,method,url,headers,body):
        self.calls.append((method,url,headers,body));status,hs,b=self.replies.pop(0)
        return Response(url,status,hs,b.encode())
    def close(self):pass
def login_replies():
    return [(302,[('Location',BASE+'/dynamic/entry')],''),
            (200,[], '<form action="challenge-new.jsp" method="post"><input name="UserID" value=""></form>'),
            (200,[('Set-Cookie','pre=one; Path=/')], '<script>var EncryptToken="'+'A'*32+'";document.authform.userToken.value="new-token";</script><form action="verify-new.jsp" method="post"><input name="Authenticator"><input name="userToken"></form>'),
            (200,[('Set-Cookie','JSESSIONID=fresh; Path=/')], '<script>Authentication.CTCSetConfig("UserStatus","1");</script><form action="channels-new.jsp" method="post"><input name="UserToken" value="result-token"></form>')]
class ClientTests(unittest.TestCase):
    def test_dynamic_forms_and_fresh_auth(self):
        fake=Fake(login_replies())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(CONFIG,d,transport=fake);c.login()
            self.assertTrue(fake.calls[-1][1].endswith('/dynamic/verify-new.jsp'))
            body=parse_qs(fake.calls[-1][3].decode())
            self.assertEqual(body['userToken'],['new-token'])
            self.assertTrue(len(body['Authenticator'][0])>100)
            self.assertNotIn('password',body)
            self.assertEqual(c.state['channel_form']['action'],BASE+'/dynamic/channels-new.jsp')
            self.assertIn('pre=one',str(fake.calls[-1][2]))
    def test_untrusted_redirect_rejected_before_request(self):
        fake=Fake([(302,[('Location','http://evil.invalid/steal')],'')])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(CONFIG,d,transport=fake)
            with self.assertRaises(ProtocolError):c.login()
            self.assertEqual(len(fake.calls),1)
    def test_expired_cookie_recognized(self):
        fake=Fake([(302,[('Location','SessionTimeOut.jsp')],'')])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(CONFIG,d,transport=fake)
            with self.assertRaises(SessionExpired):c.request('GET',BASE+'/data')
    def test_paid_continuation_not_followed(self):
        fake=Fake([(302,[('Location','play_controlTVod.jsp?ONECEPRICE=5')],'')])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(CONFIG,d,transport=fake);c.state={'epg_base':BASE+'/EPG/jsp/'}
            with self.assertRaises(PurchaseRequired):c.catchup('1',{'id':'2','start':'20200101000000','stop':'20200101010000','status':'1'})
            self.assertEqual(len(fake.calls),1)
    def test_authenticated_refreshes_once(self):
        fake=Fake([])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(CONFIG,d,transport=fake);c.state={'ready':True};calls=[]
            c.login=lambda:calls.append('login')
            def op():
                calls.append('op')
                if len(calls)==1:raise SessionExpired()
                return 'ok'
            self.assertEqual(c.authenticated(op),'ok');self.assertEqual(calls,['op','login','op'])
    def test_authenticator_reference_vector(self):
        expected=authenticator('123456','A'*32,'testuser','S'*32,'192.0.2.33','00:11:22:33:44:55','12345678')
        # Structural decrypt verifies field order and padding, independent of network.
        from Crypto.Cipher import DES
        from Crypto.Util.Padding import unpad
        clear=unpad(DES.new(b'12345600',DES.MODE_ECB).decrypt(bytes.fromhex(expected)),8).decode()
        self.assertEqual(clear,'12345678$'+'A'*32+'$testuser$'+'S'*32+'$192.0.2.33$00:11:22:33:44:55$$CTC')
    def test_variable_challenge(self):
        self.assertTrue(authenticator('123456','A'*31,'testuser','S'*32,'192.0.2.33','00:11:22:33:44:55'))
        for value in ('','abc\n','abc\x00'):
            with self.assertRaises(ValueError):authenticator('123456',value,'testuser','S'*32,'192.0.2.33','00:11:22:33:44:55')
    def test_variable_stb_id_preserved_in_encrypted_fields(self):
        from Crypto.Cipher import DES
        from Crypto.Util.Padding import unpad
        for value in ('R','Router-2','box.example','S'*32,'S'*64):
            encrypted=authenticator('123456','A'*32,'testuser',value,'192.0.2.33','00:11:22:33:44:55','12345678')
            clear=unpad(DES.new(b'12345600',DES.MODE_ECB).decrypt(bytes.fromhex(encrypted)),8).decode()
            self.assertEqual(clear.split('$')[3],value)
        for value in ('','Router 2','a$b','a\n','a\x00','盒子'):
            with self.assertRaises(ValueError):authenticator('123456','A'*32,'testuser',value,'192.0.2.33','00:11:22:33:44:55')
    def test_discovery_only_from_eds_and_scoped(self):
        config={**CONFIG,'discovery':[{'network':'10.15.250.0/24','port':33200}]}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            c=Client(config,d,transport=Fake([]))
            c._discover(CONFIG['entry_url'],'http://10.15.250.237:33200/EPG/a')
            c._trust('http://10.15.250.237:33200/EPG/a')
            for source,target in [(BASE+'/data','http://10.15.250.238:33200/a'),(CONFIG['entry_url'],'http://10.15.251.1:33200/a'),(CONFIG['entry_url'],'http://user@10.15.250.239:33200/a')]:
                c._discover(source,target)
                with self.assertRaises(ProtocolError):c._trust(target)
if __name__=='__main__':unittest.main()

