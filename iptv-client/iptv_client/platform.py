"""Layer one: authentication, discovery and single EPG queries. No publishing."""
import json,time
from http.client import HTTPException
from pathlib import Path
from .client import Client,SessionExpired,ProtocolError,atomic_text,session_identity
from .catalog import business_catalog,catchup_template

def catalog_counts(catalog):
    channels=catalog['channels']
    return {'groups':len({g for ch in channels for g in ch.get('groups',[]) if g}),
            'live':sum(bool(ch.get('live_url')) for ch in channels),
            'catchup':sum(bool(catchup_template(ch)) for ch in channels)}

class PlatformService:
    def __init__(self,config,state,transport_factory=None,client_factory=Client,catalog_loader=business_catalog):
        self.config=config;self.state=Path(state);self.path=self.state/'platform.private.json'
        self.identity=session_identity(config,'')
        self.transport_factory=transport_factory;self.client_factory=client_factory;self.catalog_loader=catalog_loader
        self.client=None;self.context=None;self.catalog=None
    def __enter__(self):return self
    def __exit__(self,*args):
        if self.context:self.context.__exit__(*args)
    def _client(self):
        if self.client is None:
            kwargs={'transport':self.transport_factory()} if self.transport_factory else {}
            self.context=self.client_factory(self.config,self.state/'session',**kwargs)
            self.client=self.context.__enter__()
            self.client.auto_reauthenticate=False
        return self.client
    def _record(self,status,snapshot=None,error=None):
        try:previous=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):previous={}
        if snapshot is None and previous.get('identity')==self.identity:snapshot=previous.get('snapshot')
        value={'identity':self.identity,'status':status,'checked':time.time(),'snapshot':snapshot,'error':error}
        atomic_text(self.path,json.dumps(value,ensure_ascii=False))
        return value
    def refresh(self,force_login=False):
        try:
            client=self._client()
            if force_login:client.login()
            try:catalog=self.catalog_loader(client)
            except SessionExpired:
                client.login();catalog=self.catalog_loader(client)
            if not catalog.get('channels'):raise ProtocolError('Empty platform channel catalog')
            counts=catalog_counts(catalog)
            snapshot={'at':time.time(),'counts':counts,'catalog':catalog}
        except Exception as error:
            status='unreachable' if isinstance(error,(OSError,HTTPException)) else 'unauthenticated' if isinstance(error,ValueError) else 'failed'
            self._record(status,error=type(error).__name__)
            raise
        self.catalog=catalog
        return self._record('authenticated',snapshot)
    def epg(self,channel,date):
        """One request. Ordinary EPG errors never mutate platform status."""
        try:return self._client().epg(channel,date)
        except SessionExpired:
            # Explicit session expiry is the sole EPG escalation to layer one.
            self._record('unauthenticated',error='SessionExpired')
            self.refresh(force_login=True)
            try:return self._client().epg(channel,date)
            except SessionExpired:
                self._record('failed',error='SessionExpired')
                raise
