"""Generate public, clearly labelled fixture captures through real Chromium.

Run explicitly; does not enable any fixture network bypass in the application.
"""
import asyncio
import json
import time
import secrets
from traceapp.db import init,connect
from traceapp.queue import schedule,claim,complete
from tests.fixtures import FixtureRenderer

async def main():
    init()
    import sys
    if '--reset-demo' in sys.argv:
        with connect() as db:
            db.execute("DELETE FROM monitors WHERE public=1 AND url LIKE 'https://fixture.trace.test/%'")
    for kind,title in [('scholarship','Meridian scholarship'),('release','Studio release notes'),('event','Design systems workshop')]:
        url=f'https://fixture.trace.test/{kind}'
        with connect() as db:
            existing=db.execute('SELECT id FROM monitors WHERE url=? AND public=1',(url,)).fetchone()
            if existing: continue
            now=time.time()
            mid=db.execute('INSERT INTO monitors(name,url,interval,config,next_due,created,public) VALUES (?,?,?,?,?,?,1)',
                (title,url,60,json.dumps({'timestamps':True,'ads':True,'counters':True,'tokens':True,'watch':[],'ignore':[],'threshold':0,'banners':False}),now+86400,now)).lastrowid
        renderer=FixtureRenderer(kind)
        for stage in (0,1):
            renderer.stage=stage;renderer.noise=stage*12
            capture=await renderer.capture(url)
            token=secrets.token_hex(16)
            with connect() as db:
                jid=db.execute("INSERT INTO jobs(monitor_id,state,due,lease,attempts,revision,token) VALUES (?,'running',?,?,1,1,?)",(mid,time.time(),time.time()+120,token)).lastrowid
            complete({'id':jid,'monitor_id':mid,'token':token},capture=capture)
        with connect() as db:
            db.execute('UPDATE monitors SET paused=1 WHERE id=?',(mid,));db.execute('DELETE FROM jobs WHERE monitor_id=?',(mid,))
        print(f'Created real fixture captures: {title}')
if __name__=='__main__':asyncio.run(main())
