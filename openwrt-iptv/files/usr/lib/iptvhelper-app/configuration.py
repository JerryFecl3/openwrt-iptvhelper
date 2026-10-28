"""Shared backend validation; messages name fields and never echo credentials."""
import ipaddress,re
from urllib.parse import urlsplit
from scheduler import daily_times,DEFAULT_TIMES
DEFAULTS={'enabled':'0','route_table':'42420','collect_times':DEFAULT_TIMES,'past_days':'7','future_days':'3','interface':'iptv','relay_listen':'0.0.0.0','relay_port':'5141'}
def defaults(settings):
    return dict(settings,**{k:v for k,v in DEFAULTS.items() if settings.get(k) in (None,'',[])})

class InvalidConfiguration(ValueError):
    def __init__(self,errors):self.errors=errors;super().__init__('Invalid configuration: '+', '.join(sorted(errors)))

def url_error(value,platform=False):
    try:
        if not value or re.search(r'\s',value):return '请输入完整地址，不允许空格'
        u=urlsplit(value)
        if u.scheme not in (('http',) if platform else ('http','https')):return '当前平台适配器仅支持 HTTP' if platform else '仅支持 HTTP 或 HTTPS'
        if not u.hostname or u.username or u.password or u.query or u.fragment:return '地址不能包含账号、查询参数或片段'
        if u.port is not None and not 1<=u.port<=65535:return '端口必须为 1–65535'
        host=u.hostname
        try:ipaddress.ip_address(host)
        except ValueError:
            if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in host.rstrip('.').split('.')):return '主机名格式无效'
    except (ValueError,TypeError):return '地址或端口格式无效'
    return None

def errors(settings,require_platform=True,include_identity=True):
    s=defaults(settings);result={}
    value=str(s.get('route_table','42420'))
    if not value.isdigit() or not 1<=int(value)<=4294967295 or int(value) in (253,254,255):result['route_table']='路由表号无效或为系统保留值'
    try:daily_times(s)
    except ValueError:result['collect_times']='请至少填写一个每日采集时间，格式为 HH:MM（00:00–23:59）'
    for key,lo,hi in [('past_days',0,7),('future_days',0,7),('relay_port',1,65535)]:
        value=str(s.get(key,''))
        if not re.fullmatch(r'[0-9]+',value) or not lo<=int(value)<=hi:result[key]=f'请输入 {lo}–{hi} 范围内的整数'
    if not re.fullmatch(r'[A-Za-z0-9_]+',s.get('interface','')):result['interface']='接口名称只能包含字母、数字和下划线'
    try:ipaddress.IPv4Address(s['relay_listen'])
    except ValueError:result['relay_listen']='请输入 IPv4 监听地址'
    if s.get('dns_override'):
        try:ipaddress.IPv4Address(s['dns_override'])
        except ValueError:result['dns_override']='请输入 IPv4 DNS 地址'
    for key,check,message in [
        ('user_id',lambda v:bool(re.fullmatch(r'[!-~]{1,128}',v)) and '$' not in v,'账号必须为不含空格和 $ 的 ASCII 字符，最多 128 字符'),
        ('password',lambda v:bool(re.fullmatch(r'[0-9]{6}',v)),'业务密码必须为 6 位数字'),
        ('stb_id',lambda v:bool(re.fullmatch(r'[!-~]+',v)) and '$' not in v,'机顶盒 ID 不能为空，须为不含空格、控制字符和 $ 的 ASCII 字符'),
        ('mac',lambda v:bool(re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',v)),'无法取得有效的机顶盒 MAC 地址；请检查所选接口')]:
        value=s.get(key,'')
        if key in ('stb_id','mac') and not include_identity:continue
        if (require_platform or value) and not check(value):result[key]=message
    for key,required,platform in [('entry_url',require_platform,True)]:
        if required or s.get(key):
            error=url_error(s.get(key,''),platform)
            if error:result[key]=error
    return result

def validate(settings,require_platform=True,include_identity=True):
    result=errors(settings,require_platform,include_identity)
    if result:raise InvalidConfiguration(result)
    return defaults(settings)
