"""Layer two collection: platform queries and database writes; never publishes."""
import datetime as dt,json,time
from pathlib import Path
from .client import atomic_text
from .catalog import catchup_template
from .epg_store import Store,fresh,ordered_dates
TZ=dt.timezone(dt.timedelta(hours=8))

def collect_data(config, state, dates, platform):
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    today=dt.datetime.now(TZ).strftime('%Y%m%d')
    dates=ordered_dates(dates or [today],today)
    summary={'started':dt.datetime.now(TZ).isoformat(),'dates':dates,'requests':0,'cached':0,'stale':[],'empty':[],'errors':[],'success':False}
    catalog=platform.catalog
    if not catalog:raise ValueError('Layer one must discover the catalog before collection')
    store=Store(config.get('epg_database',state/'epg.sqlite3'))
    try:
        if config.get('source_id'):store.bind_source(config['source_id'])
        store.save_channels(catalog,time.time())
        channels=store.channels()
        summary['warnings']=catalog.get('warnings',[])
        if not config.get('epg_database'):store.migrate(state/'epg-cache')
        summary['pruned']=store.prune(today)
        transport_failures=0;abort_error=None
        for day in dates:
            for index,channel in enumerate(channels):
                ident=str(channel['id']);previous=store.get(ident,day)
                if previous and fresh(previous['fetched_at'],day,today,time.time()):summary['cached']+=1
                elif abort_error:
                    summary['stale' if previous and previous['epg']['programmes'] else 'errors'].append({'channel':ident,'date':day,'error':'CollectionAborted'})
                else:
                    for attempt in range(3):
                        time.sleep(max(0.5,config.get('request_interval',0.75))*(attempt+1))
                        try:
                            epg=platform.epg(ident,day)
                            store.success(ident,day,epg,time.time());summary['requests']+=1;transport_failures=0
                            break
                        except Exception as error:
                            if attempt==2 or isinstance(error,ConnectionError):
                                row={'channel':ident,'date':day,'error':type(error).__name__}
                                summary['stale' if previous and previous['epg']['programmes'] else 'errors'].append(row)
                                transport_failures=transport_failures+1 if isinstance(error,(TimeoutError,ConnectionError)) else 0
                                if isinstance(error,ConnectionError) or transport_failures>=3:
                                    abort_error=type(error).__name__;summary['aborted']=abort_error
                                break
                if (index+1)%25==0 or index+1==len(channels):
                    atomic_text(state/'progress.json',json.dumps({'date':day,'done':index+1,'total':len(channels)}))
        # Export only after queries finish, and only from committed database records.
        programme_count=0
        for day in dates:
            for channel in channels:
                row=store.get(channel['id'],day)
                if row:
                    programme_count+=len(row['epg']['programmes'])
                    if not row['epg']['programmes']:summary['empty'].append({'channel':str(channel['id']),'date':day})
        summary.update(channels=len(channels),programmes=programme_count,catchup_channels=sum(bool(catchup_template(c)) for c in channels),finished=dt.datetime.now(TZ).isoformat())
        failed=len(summary['errors'])+len(summary['stale'])
        summary['epg_status']='failed' if failed and not summary['requests'] and not summary['cached'] else 'partial' if failed else 'ok'
        summary['channel_status']='partial' if summary['warnings'] else 'ok'
        summary['success']=not failed and not summary['warnings']
        atomic_text(state/'last-run.json',json.dumps(summary,ensure_ascii=False,indent=2))
        return summary
    finally:store.close()

