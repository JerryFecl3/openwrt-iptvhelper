"""Daily wall-clock slots. No interval, random delay or scheduler retry."""
import datetime as dt,hashlib,json,re
DEFAULT_TIMES=['08:00']
GROUPS={'platform':('entry_url','user_id','password','stb_id','mac','interface','dns_override'),
        'range':('past_days','future_days')}
def fingerprints(settings):
    return {name:hashlib.sha256(json.dumps([settings.get(k,'') for k in keys]).encode()).hexdigest() for name,keys in GROUPS.items()}
def daily_times(settings):
    value=settings.get('collect_times',DEFAULT_TIMES)
    if isinstance(value,str):value=value.split()
    if not isinstance(value,list) or not value or any(not isinstance(v,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',v) for v in value):
        raise ValueError('Invalid daily collection times')
    return sorted(set(value))
class Scheduler:
    def __init__(self,state=None,*unused):
        state=state or {}
        self.last_slot=state.get('last_slot','')
        self.config=state.get('config',{})
        self.history=state.get('history',[])[-32:]
        self.pending=None;self.times=list(DEFAULT_TIMES)
    def recover(self):
        # Only call after acquiring the execution lock.
        changed=False
        for record in self.history:
            if record.get('result')=='running':record['result']='interrupted';changed=True
        return changed
    def configure(self,settings,now=None):
        self.times=daily_times(settings);new=fingerprints(settings)
        if self.config:
            changed={k for k in new if new[k]!=self.config.get(k)}
            if changed & {'platform','range'}:self.pending='collect'
        self.current_config=new
    def latest_slot(self,wall):
        now=dt.datetime.fromtimestamp(wall)
        day=now.date()
        eligible=[t for t in self.times if t<=now.strftime('%H:%M')]
        if not eligible:day-=dt.timedelta(days=1)
        return day.isoformat()+' '+(eligible[-1] if eligible else self.times[-1])
    def due(self,wall,enabled,manual=False):
        if manual:return 'collect'
        if self.pending:return self.pending
        if enabled and self.latest_slot(wall)>self.last_slot:return 'collect'
        return None
    def started(self,wall,job,enabled,reason):
        slot=self.latest_slot(wall) if job=='collect' and enabled else None
        if slot:self.last_slot=max(self.last_slot,slot)
        self.config=self.current_config;self.pending=None
        self.history.append({'started':wall,'local_started':dt.datetime.fromtimestamp(wall).isoformat(timespec='seconds'),
                             'job':job,'reason':reason,'slot':slot,'result':'running'})
        self.history=self.history[-32:]
    def finished(self,wall,job,result,enabled):
        if job=='collect' and enabled:self.last_slot=max(self.last_slot,self.latest_slot(wall))
        self.history[-1].update(finished=wall,result=result.get('phase','failed'),attempts=result.get('attempts',1),covered_through=self.last_slot)
    def dump(self,*unused):return {'version':2,'last_slot':self.last_slot,'config':self.config,'history':self.history}
    def project(self,wall,enabled,stamp):
        next_run=None
        if enabled:
            now=dt.datetime.fromtimestamp(wall)
            for n in range(3):
                day=now.date()+dt.timedelta(days=n)
                for t in self.times:
                    key=day.isoformat()+' '+t
                    candidate=dt.datetime.strptime(key,'%Y-%m-%d %H:%M').timestamp()
                    if key>self.last_slot and candidate>wall:
                        next_run=stamp(candidate);break
                if next_run:break
            if self.latest_slot(wall)>self.last_slot:next_run=stamp(wall)
        return {'next_run':next_run,'collect_times':self.times,'last_execution':self.history[-1] if self.history else None}
