"""Database projection into the two local rtp2httpd source files."""
from iptv_client.epg_store import read_snapshot
from iptv_client.publisher import playlist
from iptv_client.parsing import export_xmltv

def generate(config,dates,summary,updated):
    channels,entries=read_snapshot(config['epg_database'],config.get('source_id'),dates)
    programmes=[];coverage=[]
    errors={key:{(str(x['channel']),x['date']) for x in summary.get(key,[])} for key in ('errors','stale')}
    for day in dates:
        row={'date':day,'with_programmes':0,'empty':0,'failed':0,'stale':0}
        for ch in channels:
            key=(str(ch['id']),day);cache=entries.get(key)
            items=cache['epg']['programmes'] if cache else []
            programmes.extend(items)
            row['with_programmes' if items else 'empty']+=1
            row['failed']+=key in errors['errors']
            row['stale']+=key in errors['stale']
        coverage.append(row)
    source_config={k:v for k,v in config.items() if k not in ('udpxy_base','rtp2httpd_base','media_base')}
    source_channels=[]
    for channel in channels:
        channel=dict(channel)
        url=channel.get('live_url','')
        if url.startswith('igmp://'):channel['live_url']='udp://'+url[7:]
        source_channels.append(channel)
    files={'playlist.m3u':playlist(source_channels,source_config)}
    if programmes:files['epg.xml']=export_xmltv(channels,programmes)
    return files,{'channels':len(channels),'programmes':len(programmes),'source_id':config.get('source_id'),'coverage':coverage}
