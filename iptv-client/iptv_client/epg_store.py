"""One checked programme set per channel and date, backed by SQLite."""
import datetime as dt
import json
import hashlib
import os
import time
import sqlite3
from pathlib import Path

def ordered_dates(dates,today):
    return sorted(set(dates),key=lambda d:(0 if d==today else 1 if d>today else 2,abs((dt.datetime.strptime(d,'%Y%m%d')-dt.datetime.strptime(today,'%Y%m%d')).days)))

def fresh(checked,day,today,now):
    distance=abs((dt.datetime.strptime(day,'%Y%m%d')-dt.datetime.strptime(today,'%Y%m%d')).days)
    ttl=0 if distance==0 else 43200 if distance==1 else 86400
    return checked is not None and 0<=now-checked<ttl

def source_identity(config):
    # Password changes do not change the programme data owner.
    fields=[config.get(k,'') for k in ('entry_url','user_id','stb_id','mac')]
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False).encode()).hexdigest()

class Store:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=15)
        os.chmod(path,0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS epg(channel TEXT NOT NULL, day TEXT NOT NULL, checked REAL NOT NULL, data TEXT NOT NULL, PRIMARY KEY(channel,day))')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, position INTEGER NOT NULL, checked REAL NOT NULL, data TEXT NOT NULL)')
        self.db.commit()
    def close(self):self.db.close()
    def get(self,channel,day):
        row=self.db.execute('SELECT checked,data FROM epg WHERE channel=? AND day=?',(str(channel),day)).fetchone()
        return {'fetched_at':row[0],'epg':json.loads(row[1])} if row else None
    def success(self,channel,day,epg,now):
        old=self.get(channel,day)
        data=old['epg'] if old and not epg['programmes'] else epg
        with self.db:self.db.execute('INSERT OR REPLACE INTO epg VALUES(?,?,?,?)',(str(channel),day,now,json.dumps(data,ensure_ascii=False)))
    def migrate(self,folder):
        if self.db.execute("SELECT 1 FROM meta WHERE key='json_migrated'").fetchone():return
        with self.db:
            for path in Path(folder).glob('*.json'):
                try:
                    item=json.loads(path.read_text(encoding='utf-8'));channel,day=path.stem.rsplit('-',1)
                    dt.datetime.strptime(day,'%Y%m%d')
                    if str(item['epg']['channel_id'])!=channel:continue
                    self.db.execute('INSERT OR IGNORE INTO epg VALUES(?,?,?,?)',(channel,day,float(item['fetched_at']),json.dumps(item['epg'],ensure_ascii=False)))
                except (ValueError,KeyError,TypeError):continue
            self.db.execute("INSERT INTO meta VALUES('json_migrated','1')")

    def channels(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM channels ORDER BY position')]
    def save_channels(self, catalog, now):
        channels = catalog['channels']
        ids = [str(ch['id']) for ch in channels]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Empty or duplicate channel catalog')
        previous = {str(ch['id']): ch for ch in self.channels()}
        enrichment = catalog.get('enrichment', {})
        values = []
        for position, original in enumerate(channels):
            ch = dict(original); ident = str(ch['id']); old = previous.get(ident, {})
            for source, fields in [('groups', ['groups']), ('catchup', ['catchup_catalog_member'])]:
                if enrichment.get(source) is False:
                    for field in fields:
                        if field in old: ch[field] = old[field]
            values.append((ident, position, now, json.dumps(ch, ensure_ascii=False)))
        with self.db:
            self.db.execute('DELETE FROM channels')
            self.db.executemany('INSERT INTO channels VALUES(?,?,?,?)', values)

    def bind_source(self, identity, adopt=False):
        row=self.db.execute("SELECT value FROM meta WHERE key='source_id'").fetchone()
        if row and row[0]!=identity:raise ValueError('Database source mismatch')
        if not row:
            populated=self.db.execute('SELECT EXISTS(SELECT 1 FROM channels) OR EXISTS(SELECT 1 FROM epg)').fetchone()[0]
            if populated and not adopt:raise ValueError('Unscoped database requires explicit migration')
            with self.db:self.db.execute("INSERT INTO meta VALUES('source_id',?)",(identity,))

    def prune(self,today):
        day=dt.datetime.strptime(today,'%Y%m%d')
        lower=(day-dt.timedelta(days=9)).strftime('%Y%m%d')
        upper=(day+dt.timedelta(days=9)).strftime('%Y%m%d')
        with self.db:
            deleted=self.db.execute('DELETE FROM epg WHERE day<? OR day>?',(lower,upper)).rowcount
        # Reuse free pages normally; compact only monthly and above 4 MiB/25% waste.
        row=self.db.execute("SELECT value FROM meta WHERE key='last_vacuum'").fetchone()
        now=time.time();free=self.db.execute('PRAGMA freelist_count').fetchone()[0]
        pages=self.db.execute('PRAGMA page_count').fetchone()[0]
        size=self.db.execute('PRAGMA page_size').fetchone()[0]
        if now-float(row[0] if row else 0)>30*86400 and free*size>4*1024*1024 and free>pages/4:
            self.db.execute('VACUUM')
            with self.db:self.db.execute("INSERT OR REPLACE INTO meta VALUES('last_vacuum',?)",(str(now),))
        return deleted


def read_snapshot(path,identity,dates):
    """One read-only SQLite transaction supplies a consistent publication snapshot."""
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    db=sqlite3.connect(uri,uri=True,timeout=15)
    try:
        db.execute('BEGIN')
        if identity:
            row=db.execute("SELECT value FROM meta WHERE key='source_id'").fetchone()
            if not row or row[0]!=identity:raise ValueError('Database source mismatch')
        channels=[json.loads(row[0]) for row in db.execute('SELECT data FROM channels ORDER BY position')]
        if not channels:raise ValueError('No stored channels for this source')
        ids={str(ch['id']) for ch in channels};entries={}
        for day in dates:
            for channel,checked,data in db.execute('SELECT channel,checked,data FROM epg WHERE day=?',(day,)):
                if channel in ids:entries[(channel,day)]={'fetched_at':checked,'epg':json.loads(data)}
        return channels,entries
    finally:db.close()
