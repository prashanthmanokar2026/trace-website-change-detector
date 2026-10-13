import json
import difflib
import random
import secrets
import time
from urllib.parse import urlsplit
from .db import connect
from .config import DOMAIN_DELAY, RETENTION, BASE_URL
from .content import extract
from detector.core import compare


def enqueue(db, monitor, now):
    db.execute('INSERT OR IGNORE INTO jobs(monitor_id,due,revision) VALUES (?,?,?)',
               (monitor['id'],now,monitor['revision']))

def schedule(now=None):
    now=now or time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('SELECT * FROM monitors WHERE paused=0 AND next_due<=?',(now,)).fetchall():
            enqueue(db,row,now)
            db.execute('UPDATE monitors SET next_due=? WHERE id=?',(now+row['interval']*60,row['id']))
        for dead in db.execute("SELECT * FROM jobs WHERE state='running' AND lease<? AND attempts>=3",(now,)).fetchall():
            db.execute("UPDATE monitors SET status='error',reason='Worker interrupted repeatedly; check limits and restart' WHERE id=?",(dead['monitor_id'],))
            db.execute("INSERT INTO checks(monitor_id,checked,status,reason) VALUES (?,?,'error','Worker lease expired after maximum attempts')",(dead['monitor_id'],now))
            db.execute('DELETE FROM jobs WHERE id=?',(dead['id'],))
        db.execute("UPDATE jobs SET state='pending',token=NULL,lease=NULL WHERE state='running' AND lease<?",(now,))
        db.execute("INSERT OR REPLACE INTO meta VALUES ('worker_heartbeat',?)",(str(now),))

def claim(now=None):
    now=now or time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        candidates=db.execute("SELECT j.*,m.url FROM jobs j JOIN monitors m ON m.id=j.monitor_id WHERE j.state='pending' AND j.due<=? AND m.paused=0 ORDER BY j.due LIMIT 500",(now,)).fetchall()
        for first in candidates:
            host=urlsplit(first['url']).hostname
            limit=db.execute('SELECT next_allowed FROM domains WHERE host=?',(host,)).fetchone()
            if limit and limit[0]>now: continue
            group=[dict(r) for r in candidates if r['url']==first['url']]
            token=secrets.token_hex(16)
            for job in group:
                job['token']=token
                db.execute("UPDATE jobs SET state='running',token=?,lease=?,attempts=attempts+1 WHERE id=?",(token,now+120,job['id']))
            db.execute('INSERT OR REPLACE INTO domains VALUES (?,?)',(host,now+DOMAIN_DELAY))
            return group
    return []

def complete(job,capture=None,error=None,now=None):
    now=now or time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        active=db.execute('SELECT * FROM jobs WHERE id=? AND token=?',(job['id'],job['token'])).fetchone()
        monitor=db.execute('SELECT * FROM monitors WHERE id=?',(job['monitor_id'],)).fetchone()
        if not active or not monitor: return
        if monitor['paused'] or monitor['revision']!=active['revision']:
            db.execute('DELETE FROM jobs WHERE id=?',(active['id'],)); return
        version_id=None; meaningful=False
        if error is None:
            try:
                conf=json.loads(monitor['config'])
                text,masks=extract(capture.html,capture.geometry,conf)
                old=db.execute('SELECT * FROM versions WHERE monitor_id=? AND revision=? ORDER BY id DESC LIMIT 1',
                               (monitor['id'],monitor['revision'])).fetchone()
                result=compare(old['text'] if old else None,text,significant_baseline=monitor['significant_text'],threshold=conf.get('threshold',0))
                meaningful=result.meaningful
                reason='Baseline saved' if old is None else ('Meaningful change' if meaningful else ('Below alert threshold' if result.new_version else 'Unchanged after filtering'))
                status='ok'
                if result.new_version:
                    used=db.execute('SELECT COALESCE(sum(length(image)+length(html)),0) FROM versions').fetchone()[0]
                    if used+len(capture.image)+len(capture.html)>512*1024*1024:
                        raise ValueError('Capture storage limit reached (512 MB); remove old monitors or reduce retention')
                    version_id=db.execute('''INSERT INTO versions(monitor_id,revision,captured,text,hash,image,geometry,html,meaningful,reason,masks)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(monitor['id'],monitor['revision'],capture.captured,text,result.content_hash,
                        capture.image,json.dumps(capture.geometry),capture.html,int(meaningful),reason,json.dumps(masks))).lastrowid
                if old is None or meaningful:
                    db.execute('UPDATE monitors SET significant_text=? WHERE id=?',(text,monitor['id']))
                if meaningful:
                    db.execute('UPDATE monitors SET last_changed=? WHERE id=?',(now,monitor['id']))
                    settings=dict(db.execute('SELECT key,value FROM settings').fetchall())
                    for channel in ('email','discord'):
                        if settings.get(channel)=='on' and not monitor['public']:
                            added=[line[2:] for line in difflib.ndiff(old['text'].splitlines(),text.splitlines()) if line.startswith('+ ')]
                            summary=('Added or updated: '+'; '.join(added))[:350] if added else 'Text was removed from the monitored region.'
                            body=f"{monitor['name']}: content changed ({result.changed_fraction:.0%} of compared tokens).\n{summary}\n{BASE_URL}/?monitor={monitor['id']}&before={old['id']}&after={version_id}"
                            db.execute('INSERT OR IGNORE INTO outbox(monitor_id,version_id,channel,body,due,before_id) VALUES (?,?,?,?,?,?)',
                                       (monitor['id'],version_id,channel,body,max(now,(db.execute('SELECT COALESCE(max(due),0) FROM outbox WHERE monitor_id=? AND channel=?',(monitor['id'],channel)).fetchone()[0])+600),old['id']))
            except ValueError as exc:
                error=exc
        if error is not None:
            status='blocked' if getattr(error,'blocked',False) else 'error'
            # Error strings from remote libraries can contain full query credentials.
            reason=str(error) if isinstance(error,ValueError) or hasattr(error,'blocked') else 'Capture failed or timed out; retry will be bounded'
        db.execute('UPDATE monitors SET status=?,reason=?,last_checked=? WHERE id=?',(status,reason,now,monitor['id']))
        db.execute('INSERT INTO checks(monitor_id,checked,status,reason,version_id) VALUES (?,?,?,?,?)',(monitor['id'],now,status,reason,version_id))
        retry_after=getattr(error,'retry_after',0) if error else 0
        if error and status!='blocked' and not isinstance(error,ValueError) and active['attempts']<3:
            due=now+max(retry_after,30*2**active['attempts']+random.uniform(0,10))
            db.execute("UPDATE jobs SET state='pending',due=?,lease=NULL,token=NULL WHERE id=?",(due,active['id']))
        else:
            db.execute('DELETE FROM jobs WHERE id=?',(active['id'],))
        if retry_after:
            db.execute('INSERT OR REPLACE INTO domains VALUES (?,?)',(urlsplit(monitor['url']).hostname,now+retry_after))
        db.execute('DELETE FROM versions WHERE monitor_id=? AND id NOT IN (SELECT id FROM versions WHERE monitor_id=? ORDER BY id DESC LIMIT ?) AND id NOT IN (SELECT version_id FROM outbox WHERE state!=\'sent\' UNION SELECT before_id FROM outbox WHERE state!=\'sent\' AND before_id IS NOT NULL)',
                   (monitor['id'],monitor['id'],RETENTION))
        db.execute('DELETE FROM checks WHERE monitor_id=? AND id NOT IN (SELECT id FROM checks WHERE monitor_id=? ORDER BY id DESC LIMIT 200)',(monitor['id'],monitor['id']))
