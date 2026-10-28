"""HTTP transports. SSH helper is temporary and standard-library-only on router."""
import base64,http.client,json,socket,subprocess,threading,queue
from pathlib import Path
from urllib.parse import urlsplit
from dataclasses import dataclass

@dataclass
class Response:
    url:str
    status:int
    headers:list
    body:bytes
    def header(self,name,default=''):
        return next((v for k,v in self.headers if k.lower()==name.lower()),default)

class DirectTransport:
    def __init__(self,config):
        self.config=config;self.source_ip=config.get('source_ip')
        self.device=config.get('device')
        if config.get('interface'):
            st=json.loads(subprocess.check_output(['ubus','call','network.interface.'+config['interface'],'status'],text=True))
            if not st.get('up'):raise RuntimeError('IPTV interface is down')
            self.source_ip=st['ipv4-address'][0]['address'];self.device=st['l3_device']
    def request(self,method,url,headers=None,body=b''):
        u=urlsplit(url); port=u.port or (443 if u.scheme=='https' else 80)
        target=self.config.get('connect_ips',{}).get(u.hostname,u.hostname)
        source=(self.source_ip,0) if self.source_ip else None
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        s.settimeout(self.config.get('timeout',15))
        if self.device:s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,self.device.encode()+b'\0')
        if source:s.bind(source)
        try:
            s.connect((target,port))
            if u.scheme=='https':
                import ssl
                s=ssl.create_default_context().wrap_socket(s,server_hostname=u.hostname)
            h={'Host':u.netloc,'Connection':'close',**(headers or {})}
            if body:h['Content-Length']=str(len(body))
            if any('\r' in str(v) or '\n' in str(v) for v in h.values()):raise ValueError('Invalid header')
            path=(u.path or '/')+('?' + u.query if u.query else '')
            s.sendall((method+' '+path+' HTTP/1.1\r\n'+''.join(k+': '+str(v)+'\r\n' for k,v in h.items())+'\r\n').encode()+body)
            r=http.client.HTTPResponse(s);r.begin();data=r.read(self.config.get('max_response_bytes',8000000)+1)
            if len(data)>self.config.get('max_response_bytes',8000000):raise ValueError('Response exceeds limit')
            return Response(url,r.status,r.getheaders(),data)
        finally:s.close()
    def close(self):pass

class SSHTransport:
    def __init__(self,config):
        self.config=config
        script=(Path(__file__).with_name('ssh_worker.py')).read_bytes()
        encoded=base64.b64encode(script).decode()
        command="python3 -u -c \"import base64;exec(base64.b64decode('"+encoded+"'))\""
        args=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2']
        if config.get('known_hosts'):args+=['-o','UserKnownHostsFile='+config['known_hosts']]
        args += [config['host'],command]
        self.proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.replies=queue.Queue();self.diagnostics=[]
        def stdout_reader():
            for line in self.proc.stdout:self.replies.put(line)
            self.replies.put(None)
        def stderr_reader():
            for line in self.proc.stderr:
                if len(self.diagnostics)<20:self.diagnostics.append(line[:1000])
        threading.Thread(target=stdout_reader,daemon=True).start()
        threading.Thread(target=stderr_reader,daemon=True).start()
        try:response=self._exchange({'op':'init','config':config})
        except Exception:
            self.proc.stdin.close()
            try:self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:self.proc.terminate()
            raise
        self.source_ip=response['source_ip']
    def _exchange(self,item):
        self.proc.stdin.write(json.dumps(item)+'\n');self.proc.stdin.flush()
        try:line=self.replies.get(timeout=self.config.get('timeout',15)+20)
        except queue.Empty:
            self.proc.stdin.close();self.proc.terminate()
            raise RuntimeError('SSH helper response timeout')
        if not line:
            Path('ssh-diagnostic.private.txt').write_text(''.join(self.diagnostics),encoding='utf-8')
            raise RuntimeError('SSH helper exited; inspect ssh-diagnostic.private.txt')
        result=json.loads(line)
        if 'error' in result:raise RuntimeError('Transport: '+result['error'])
        return result
    def request(self,method,url,headers=None,body=b''):
        r=self._exchange({'op':'request','method':method,'url':url,'headers':headers or {},'body':base64.b64encode(body).decode()})
        return Response(url,r['status'],r['headers'],base64.b64decode(r['body']))
    def close(self):
        if self.proc.poll() is None:
            try:self._exchange({'op':'close'})
            finally:
                self.proc.stdin.close()
                try:self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:self.proc.terminate()
        if self.proc.stdout:self.proc.stdout.close()
        if self.proc.stderr:self.proc.stderr.close()

def make_transport(config):
    return SSHTransport(config) if config.get('type')=='ssh' else DirectTransport(config)
