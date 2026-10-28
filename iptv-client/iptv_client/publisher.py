"""Scheduled file publisher. Platform client is independent of this application."""
import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path
from .client import Client, atomic_text
from .catalog import business_catalog, catchup_template
from .platform import PlatformService
from .epg_store import Store, fresh, ordered_dates
from .parsing import export_m3u, export_xmltv, export_csv, _single_line

TZ = dt.timezone(dt.timedelta(hours=8))


def playlist(channels, config):
    lines = ['#EXTM3U x-tvg-url="' + _single_line(config['epg_url']) + '"']
    for channel in channels:
        item = export_m3u([channel], config.get('rtp2httpd_base') or config.get('media_base') or config.get('udpxy_base')).splitlines()[1:]
        if not item: continue
        if config.get('rtp2httpd_base') and len(item)>1:
            if item[1].startswith('rtsp://'):
                item[1]=config['rtp2httpd_base'].rstrip('/')+'/rtsp/'+item[1][7:]
            elif item[1].startswith(('http://','https://')) and not item[1].startswith(config['rtp2httpd_base'].rstrip('/')+'/'):
                raise ValueError('Unsupported unicast live URL; refusing unproxied publication')
        attrs = ' group-title="' + _single_line(';'.join(channel['groups'])) + '"'
        attrs += ' tvg-chno="' + _single_line(channel.get('number', '')) + '"'
        template = catchup_template(channel)
        if template:
            if config.get('rtp2httpd_base'):
                template = config['rtp2httpd_base'].rstrip('/') + '/rtsp/' + template[7:]
            attrs += ' catchup="default" catchup-days="7" catchup-correction="0" catchup-source="' + _single_line(template) + '"'
        head, name = item[0].rsplit(',', 1)
        lines.extend([head + attrs + ',' + name, *item[1:]])
    return '\n'.join(lines) + '\n'


def publish(state, channels, programmes, config, summary):
    root = state / 'public'
    root.mkdir(parents=True, exist_ok=True)
    generation = root / ('generation-' + str(time.time_ns()))
    generation.mkdir(mode=0o755)
    values = {'iptv_new.m3u': playlist(channels, config)}
    previous_epg = root / 'current/epg_new.xml'
    if programmes:
        values['epg_new.xml'] = export_xmltv(channels, programmes)
    elif previous_epg.exists() and (not config.get('source_id') or (root/'current/source.json').exists() and json.loads((root/'current/source.json').read_text()).get('source_id')==config['source_id']):
        values['epg_new.xml'] = previous_epg.read_text(encoding='utf-8')
    if config.get('source_id'):values['source.json']=json.dumps({'source_id':config['source_id']})
    for name, data in values.items():
        atomic_text(generation / name, data)
        os.chmod(generation / name, 0o644)
    tmp = root / 'current.next'
    if tmp.is_symlink(): tmp.unlink()
    tmp.symlink_to(generation.name, target_is_directory=True)
    os.replace(tmp, root / 'current')
    # Retain one previous generation for quick rollback; delete only own files.
    old = sorted(root.glob('generation-*'), key=lambda p: p.name, reverse=True)
    for folder in old[2:]:
        for name in ('iptv_new.m3u', 'epg_new.xml', 'source.json'):
            (folder / name).unlink(missing_ok=True)
        folder.rmdir()



def update(config, state, dates=None, transport=None):
    """Compatibility entrypoint: explicitly run layer one, then layer two."""
    factory=(lambda: transport) if transport is not None else None
    with PlatformService(config,state,factory,client_factory=Client,catalog_loader=business_catalog) as platform:
        platform.refresh()
        return collect(config,state,dates,platform)


def collect(config,state,dates,platform):
    """Compatibility CLI orchestration. Router daemon uses independent stages."""
    from .collector import collect_data
    from .epg_store import read_snapshot
    summary=collect_data(config,state,dates,platform)
    channels,entries=read_snapshot(config.get('epg_database',Path(state)/'epg.sqlite3'),config.get('source_id'),summary['dates'])
    programmes=[p for row in entries.values() for p in row['epg']['programmes']]
    publish(Path(state),channels,programmes,config,summary)
    summary.update(published=True,epg_published=bool(programmes))
    atomic_text(Path(state)/'last-published.json',json.dumps(summary,ensure_ascii=False))
    if summary['success']:atomic_text(Path(state)/'last-success.json',json.dumps(summary,ensure_ascii=False))
    return summary


def main():
    import fcntl
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='/etc/iptvhelper/config.json')
    ap.add_argument('--state', default='/root/iptvhelper-state')
    ap.add_argument('--dates', nargs='+')
    args = ap.parse_args()
    os.umask(0o077)
    state = Path(args.state); state.mkdir(parents=True, exist_ok=True)
    with (state / 'update.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another update is already running'); return 0
        try:
            config = json.loads(Path(args.config).read_text(encoding='utf-8'))
            summary = update(config, state, args.dates)
            print(json.dumps({k: v for k, v in summary.items() if k not in ('empty', 'stale', 'errors')}, ensure_ascii=False))
            return 0 if summary['success'] else 1
        except Exception as e:
            atomic_text(state / 'last-error.json', json.dumps({'at': dt.datetime.now(TZ).isoformat(), 'error': type(e).__name__}))
            print('Update failed: ' + type(e).__name__ + '; published files preserved', flush=True)
            return 1


if __name__ == '__main__': raise SystemExit(main())
