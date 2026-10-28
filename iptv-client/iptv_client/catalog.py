"""Liaoning page adapter. No scripts from the portal are executed."""
import json
import re
from urllib.parse import urljoin, urlsplit, parse_qsl, urlencode
from .parsing import decode_html, ParseError


def business_catalog(client):
    channels = client.channels()
    warnings = []
    services = []; ids = set(); indexes = {}; rows = []
    landing_url = catchup_url = ''; catchup_ref = None
    catchup_ok = grouping_ok = False
    try:
        services = client.services()
        tvod = next((s for s in services if s['name'] == 'TVOD'), None)
        if not tvod:
            raise ParseError('TVOD service missing')
        landing = client.request('GET', tvod['url'])
        page = decode_html(landing.body)
        # Follow a reference supplied by the service page; regional leaf page names
        # remain adapter knowledge, not a claim that every endpoint is returned.
        refs = re.findall(r'''["']([^"'\s<>]+\.jsp(?:\?[^"'\s<>]*)?)["']''', page)
        catchup_ref = next((r for r in refs if r.split('?')[0].endswith('hk-channellist.jsp')), None)
        catchup_url = urljoin(landing.url, catchup_ref) if catchup_ref else urljoin(client.state['epg_base'], client.config.get('adapter', {}).get('logo_page', 'default/en/tj_pinterest/hk-channellist.jsp'))
        response = client.request('GET', catchup_url)
        catchup_page = decode_html(response.body)
        ids = set(re.findall(r'''chan(?:\.channelId|\[["']channelId["']\])\s*=\s*["'](\d+)["']''', catchup_page))
        if not ids:
            raise ParseError('Catchup catalog identity structure changed')
        landing_url = landing.url
        catchup_ok = True
    except Exception as error:
        from .client import SessionExpired
        if isinstance(error, SessionExpired): raise
        warnings.append({'source': 'catchup', 'error': type(error).__name__})
    try:
        live_path = client.config.get('adapter', {}).get('live_logo_page', 'default/en/tj_pinterest/zb-channellist.jsp')
        live = client.request('GET', urljoin(client.state['epg_base'], live_path))
        matches = re.findall(r'\bchanList\s*=\s*(\[.*?\])\s*;', decode_html(live.body), re.S)
        rows = next((json.loads(s) for s in matches if s.strip() != '[]'), [])
        if not rows:
            raise ParseError('Live grouping catalog missing')
        indexes = {str(r['channelId']): int(r['channelIndex']) for r in rows}
        grouping_ok = True
    except Exception as error:
        from .client import SessionExpired
        if isinstance(error, SessionExpired): raise
        warnings.append({'source': 'groups', 'error': type(error).__name__})
    for channel in channels:
        channel['logo'] = ''
        channel['catchup_catalog_member'] = channel['id'] in ids
        n = indexes.get(channel['id'], -1)
        groups = []
        # Conditions copied from this regional portal's grouping script.
        if 160 <= n <= 200: groups.append('精选')
        if 1 <= n <= 24 or n in (148, 149): groups.append('央视')
        if 101 <= n <= 147 or n in (303, 25) or 150 <= n <= 157: groups.append('卫视')
        if 25 <= n <= 100: groups.append('本地')
        if 201 <= n <= 224 or 49 <= n <= 52: groups.append('数字')
        channel['groups'] = groups or ['平台未分类']
    return {'warnings': warnings, 'enrichment': {'catchup': catchup_ok, 'groups': grouping_ok}, 'channels': channels, 'services': services, 'catchup_ids': sorted(ids),
            'discovery': {'entry': client.config['entry_url'], 'portal': client.state['epg_base'],
                          'tvod_landing': landing_url, 'catchup_catalog': catchup_url,
                          'catchup_reference_returned': bool(catchup_ref),
                          'regional_adapter': 'liaoning-huawei', 'grouping_rows': len(rows)}}


def catchup_template(channel):
    """Verified PLTV + playseek route; preserve dispatcher, omit account token.

    This is line-authorized direct media access, not an anonymous-service claim.
    Only expose channels appearing in the platform's catchup catalog.
    """
    if not channel.get('catchup_catalog_member') or not channel.get('timeshift_enabled'):
        return None
    u = urlsplit(channel.get('timeshift_url', ''))
    if u.scheme != 'rtsp' or not u.path.startswith('/PLTV/'):
        return None
    q = [(k, v) for k, v in parse_qsl(u.query) if k.lower() not in ('accountinfo', 'playseek')]
    # Match the existing Router1 playlist date-template dialect.
    query = urlencode(q) + '&playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}'
    return u._replace(query=query, fragment='').geturl()
