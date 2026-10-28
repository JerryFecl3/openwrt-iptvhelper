import base64,datetime,email.message,hashlib,http.cookiejar,json,os,re,secrets,time,ipaddress
from pathlib import Path
from urllib.parse import urljoin,urlsplit,urlencode,parse_qsl
from urllib.request import Request
from .auth import authenticator
from .transport import make_transport
from .parsing import decode_html,parse_forms,parse_channels,parse_services,parse_epg,parse_logos

class SessionExpired(RuntimeError):pass
class PurchaseRequired(RuntimeError):pass
class ProtocolError(RuntimeError):pass

def session_identity(config,source_ip):
    return hashlib.sha256(json.dumps([config.get('user_id'),config.get('stb_id'),config.get('mac'),source_ip,config.get('entry_url'),hashlib.sha256(config.get('password','').encode()).hexdigest()],sort_keys=True).encode()).hexdigest()

def atomic_text(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+secrets.token_hex(4)+'.tmp')
    try:
        with open(tmp,'x',encoding='utf-8',newline='') as f:
            try:os.chmod(tmp,0o600)
            except OSError:pass
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()

class CookieResponse:
    def __init__(self,response):
        self.response=response;self.message=email.message.Message()
        for k,v in response.headers:self.message.add_header(k,v)
    def info(self):return self.message

class Client:
    def __init__(self,config,state_dir,raw_dir=None,transport=None):
        for key in ('trusted_origins','user_id','password','stb_id','mac','entry_url'):
            if not config.get(key):raise ValueError('Missing required client configuration: '+key)
        for rule in config.get('discovery',[]):
            ipaddress.ip_network(rule['network']);int(rule['port'])
        self.config=config;self.state_dir=Path(state_dir);self.state_dir.mkdir(parents=True,exist_ok=True)
        self.raw_dir=(Path(raw_dir)/('session-'+secrets.token_hex(8))) if raw_dir else None
        if self.raw_dir:self.raw_dir.mkdir(parents=True,exist_ok=True)
        self.transport=transport or make_transport(config.get('transport',{}))
        self.jar=http.cookiejar.LWPCookieJar(str(self.state_dir/'cookies.private.txt'))
        self.state={};self.counter=0
        self.allowed=set(config['trusted_origins'])
        self.source_ip=config.get('auth_ip') or self.transport.source_ip
        if not self.source_ip:
            self.transport.close();raise ValueError('auth_ip or transport source_ip is required')
        self.identity=session_identity(config,self.source_ip)
        try:
            state=json.loads((self.state_dir/'session.private.json').read_text(encoding='utf-8'))
            if state['identity']==self.identity and time.time()-state['created']<config.get('session_max_age',7200):
                self._discover(config['entry_url'],state['epg_base'])
                self.jar.load(ignore_discard=True,ignore_expires=False);self.state=state
        except (OSError,ValueError,KeyError,http.cookiejar.LoadError):pass
    def close(self):self.transport.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def _trust(self,url):
        u=urlsplit(url);origin=u.scheme+'://'+u.netloc
        if u.username or u.password or origin not in self.allowed:raise ProtocolError('Untrusted service origin; update trusted_origins only after review')
        return url
    def _discover(self,source,target):
        # Only an original EDS redirect can introduce an explicitly scoped node.
        a=urlsplit(source);b=urlsplit(self.config['entry_url']);u=urlsplit(target)
        if (a.scheme,a.netloc,a.path)!=(b.scheme,b.netloc,b.path):return
        if u.scheme!='http' or u.username or u.password:return
        try:addr=ipaddress.ip_address(u.hostname)
        except ValueError:return
        for rule in self.config.get('discovery',[]):
            if u.port==rule['port'] and addr in ipaddress.ip_network(rule['network']):
                self.allowed.add(u.scheme+'://'+u.netloc)
    def request(self,method,url,fields=None,follow=True,expect_session=True,send_cookies=True,referer=None):
        body=urlencode(fields).encode() if fields is not None else b''
        for hop in range(8):
            self._trust(url)
            headers={'User-Agent':self.config.get('user_agent','B700-V2A|Mozilla|5.0|ztebw|1.0.0'),'Accept-Encoding':'identity'}
            if referer:headers['Referer']=self._trust(referer)
            if fields is not None:headers['Content-Type']='application/x-www-form-urlencoded'
            cookie_request=Request(url,headers=headers)
            if send_cookies:self.jar.add_cookie_header(cookie_request)
            # Retry only idempotent GET transport failures, never authentication POST.
            for attempt in range(2):
                try:r=self.transport.request(method,url,dict(cookie_request.header_items()),body);break
                except (OSError,RuntimeError):
                    if method!='GET' or attempt:raise
                    time.sleep(1)
            if send_cookies:self.jar.extract_cookies(CookieResponse(r),cookie_request)
            self.counter+=1
            if self.raw_dir:
                raw_path=self.raw_dir/(str(self.counter).zfill(4)+'-'+Path(urlsplit(url).path).name.replace(':','_')+'.bin')
                raw_path.write_bytes(r.body)
                try:os.chmod(raw_path,0o600)
                except OSError:pass
                # metadata deliberately excludes query, Cookies, response tokens.
                atomic_text(raw_path.with_suffix('.meta.json'),json.dumps({'url_path':urlsplit(url).path,'origin':urlsplit(url).netloc,'status':r.status,'bytes':len(r.body),'content_type':r.header('content-type')},ensure_ascii=False))
            location=r.header('location')
            if expect_session and ('sessiontimeout' in location.lower() or 'sessiontimeout' in r.body[:4000].decode('ascii',errors='ignore').lower()):raise SessionExpired('Portal session expired')
            if follow and r.status in (301,302,303,307,308) and location:
                target=urljoin(url,location);self._discover(url,target);self._trust(target)
                if r.status in (301,302,303):method='GET';fields=None;body=b''
                url=target;continue
            if r.status>=400:raise ProtocolError('HTTP '+str(r.status)+' for '+urlsplit(url).path)
            return r
        raise ProtocolError('Redirect limit reached')
    def _form(self,response):
        forms=parse_forms(decode_html(response.body,response.header('content-type')),response.url)
        if len(forms)!=1:raise ProtocolError('Expected exactly one authentication continuation form')
        self._trust(forms[0]['action']);return forms[0]
    def _submit(self,form,expect_session=True):
        if form['method'].upper()=='GET':
            u=form['action'];return self.request('GET',u+('&' if '?' in u else '?')+urlencode(form['fields']),expect_session=expect_session)
        return self.request('POST',form['action'],form['fields'],expect_session=expect_session)
    def login(self):
        attempted=time.time()
        self._auth_status('authenticating')
        try:self._login()
        except Exception as error:
            self._login_status('failed',attempted,type(error).__name__)
            self._auth_status('failed' if isinstance(error,ProtocolError) else 'unavailable',type(error).__name__)
            raise
        self._login_status('authenticated',attempted)
        self._auth_status('authenticated')
    def _login_status(self,status,attempted,error=None):
        atomic_text(self.state_dir/'login-status.private.json',json.dumps({'identity':session_identity(self.config,''),'status':status,'attempted':attempted,'error':error}))
    def _auth_status(self,status,error=None):
        path=self.state_dir/'auth-status.private.json'
        try:previous=json.loads(path.read_text())
        except (OSError,ValueError):previous={}
        now=time.time()
        last_success=None
        if previous.get('identity')==self.identity:
            last_success=previous.get('last_success') or (previous.get('checked') if previous.get('status')=='authenticated' else None)
        if status=='authenticated':last_success=now
        atomic_text(path,json.dumps({'status':status,'checked':now,'last_success':last_success,
                    'identity':self.identity,'created':self.state.get('created'),'error':error}))
    def _login(self):
        self.jar.clear();self.state={}
        entry=self.config['entry_url'];params=dict(parse_qsl(urlsplit(entry).query));params.update(UserID=self.config['user_id'],Action='Login')
        u=urlsplit(entry);entry=u._replace(query=urlencode(params)).geturl()
        response=self.request('GET',entry,expect_session=False)
        login_form=self._form(response);login_form['fields']['UserID']=self.config['user_id']
        response=self._submit(login_form,expect_session=False)
        html=decode_html(response.body,response.header('content-type'));auth_form=self._form(response)
        token_match=re.search(r'\b(?:var\s+)?EncryptToken\s*=\s*["\x27]([^"\x27]+)',html)
        user_token=re.search(r'authform\.userToken\.value\s*=\s*["\x27]([^"\x27]*)',html)
        if not token_match or not user_token:raise ProtocolError('Challenge fields not found')
        f=auth_form['fields'];f.update(self.config.get('device_fields',{}))
        f.update(UserID=self.config['user_id'],STBID=self.config['stb_id'],mac=self.config['mac'],userToken=user_token.group(1))
        f['Authenticator']=authenticator(self.config['password'],token_match.group(1),self.config['user_id'],self.config['stb_id'],self.source_ip,self.config['mac'])
        response=self._submit(auth_form,expect_session=False)
        html=decode_html(response.body,response.header('content-type'))
        if not re.search(r"CTCSetConfig\(\s*['\"]UserStatus['\"]\s*,\s*['\"]1['\"]",html):raise ProtocolError('Portal did not confirm successful authentication')
        channel_form=self._form(response)
        self.state={'identity':self.identity,'created':time.time(),'epg_base':urljoin(response.url,'./'),'channel_form':channel_form}
        self._save_session()
    def _save_session(self):
        temp=str(self.jar.filename)+'.'+secrets.token_hex(4)+'.tmp'
        self.jar.save(temp,ignore_discard=True,ignore_expires=False)
        os.replace(temp,self.jar.filename)
        try:os.chmod(self.jar.filename,0o600)
        except OSError:pass
        atomic_text(self.state_dir/'session.private.json',json.dumps(self.state,ensure_ascii=False,indent=2))
    def authenticated(self,operation):
        if not self.state:self.login()
        try:
            try:result=operation()
            except SessionExpired:
                if not getattr(self,'auto_reauthenticate',True):raise
                self._auth_status('expired')
                self.login();result=operation()
        except Exception as error:
            # Do not overwrite a more specific failed login with a fetch error.
            try:current=json.loads((self.state_dir/'auth-status.private.json').read_text())
            except (OSError,ValueError):current={}
            if current.get('status') not in ('failed','unavailable'):
                self._auth_status('expired' if isinstance(error,SessionExpired) else 'unavailable',type(error).__name__)
            raise
        self._auth_status('authenticated')
        return result
    def channels(self):
        def get():
            r=self._submit(self.state['channel_form'])
            html=decode_html(r.body,r.header('content-type'));channels=parse_channels(html)
            if not channels:raise ProtocolError('Empty channel catalog; refusing to replace last good output')
            self.state['service_form']=self._form(r)
            self._save_session();return channels
        return self.authenticated(get)
    def services(self):
        def get():
            if 'service_form' not in self.state:self.channels()
            r=self._submit(self.state['service_form']);return parse_services(decode_html(r.body,r.header('content-type')),r.url)
        return self.authenticated(get)
    def epg(self,channel_id,date):
        datetime.datetime.strptime(date,'%Y%m%d')
        def get():
            path=self.config.get('adapter',{}).get('epg_path','default/en/datajsp/tvod_IchanListData-hd3.jsp')
            url=urljoin(self.state['epg_base'],path)+'?'+urlencode({'CHAN_ID':channel_id,'ISSUB':'1','TVODDATEFOCUS':'2','GETDATE':date})
            r=self.request('GET',url)
            return parse_epg(decode_html(r.body,r.header('content-type')),channel_id)
        return self.authenticated(get)
    def logos(self):
        def get():
            path=self.config.get('adapter',{}).get('logo_page','default/en/tj_pinterest/hk-channellist.jsp')
            r=self.request('GET',urljoin(self.state['epg_base'],path))
            page=decode_html(r.body,r.header('content-type'))
            self.catchup_channel_ids=sorted(set(re.findall(r'chan(?:\.channelId|\[["\x27]channelId["\x27]\])\s*=\s*["\x27](\d+)["\x27]',page)))
            logos=parse_logos(page,r.url)
            extra=self.config.get('adapter',{}).get('live_logo_page')
            if extra:
                rr=self.request('GET',urljoin(self.state['epg_base'],extra))
                logos.update(parse_logos(decode_html(rr.body,rr.header('content-type')),rr.url))
            return logos
        return self.authenticated(get)
    def catchup(self,channel_id,programme):
        if str(programme.get('status'))!='1':raise ValueError('Programme is not marked recorded')
        stop=datetime.datetime.strptime(programme['stop'],'%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        if stop>datetime.datetime.now(datetime.timezone.utc):raise ValueError('Programme has not ended')
        def get():
            path=self.config.get('adapter',{}).get('catchup_path','default/en/au_ReviewOrSubscribe.jsp')
            query={'PROGID':programme['id'],'PLAYTYPE':'4','CONTENTTYPE':'300','BUSINESSTYPE':'5','PROGSTARTTIME':programme['start'],'PROGENDTIME':programme['stop'],'ISSUB':'1','PREVIEWFLAG':'0','TVOD':'1','CHANNELID':channel_id}
            r=self.request('GET',urljoin(self.state['epg_base'],path)+'?'+urlencode(query),follow=False)
            target=urljoin(r.url,r.header('location'))
            # Only the observed playback continuation is followed; never order forms.
            if r.status not in (301,302,303) or not urlsplit(target).path.endswith('/play_controlTVod.jsp'):raise PurchaseRequired('Unexpected playback continuation; no order was submitted')
            prices=dict(parse_qsl(urlsplit(target).query))
            if prices.get('ONECEPRICE') not in (None,'','0','0.0','0.00'):raise PurchaseRequired('Nonzero price; playback not requested')
            player=self.request('GET',target,follow=False)
            if player.status!=200:raise ProtocolError('Playback page not returned')
            html=decode_html(player.body,player.header('content-type'))
            urls=re.findall(r'rtsp://[^\s"\x27<>]+',html)
            urls=[x for x in urls if '/TVOD/' in urlsplit(x).path]
            if len(set(urls))!=1:raise ProtocolError('Expected one signed TVOD URL')
            url=urls[0];q=dict(parse_qsl(urlsplit(url).query))
            if q.get('playseek')!=programme['start']+'-'+programme['stop']:raise ProtocolError('Playback time mismatch')
            return {'channel_id':channel_id,'programme_id':programme['id'],'start':programme['start'],'stop':programme['stop'],'url':url,'obtained_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'transport_hint':'RTSP over TCP','price_field':prices.get('ONECEPRICE')}
        return self.authenticated(get)
