import difflib
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from . import config
from .db import connect, init
from .policy import validate_url
from .queue import enqueue
from .content import extract, image_diff
from .notify import configured

@asynccontextmanager
async def lifespan(app):
    init(); yield

app=FastAPI(title='Trace',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
limits=defaultdict(deque)
request_limits=defaultdict(deque)

def session(request):
    token=request.cookies.get('trace_session','')
    with connect() as db:
        row=db.execute('SELECT * FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return dict(row) if row else None

def owner(request):
    user=session(request)
    if not user: raise HTTPException(401,'Sign in as owner to make changes')
    if request.method not in ('GET','HEAD') and not hmac.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
        raise HTTPException(403,'Refresh the page before making changes')
    return user

@app.middleware('http')
async def security(request,call_next):
    now=time.monotonic()
    bucket='image' if request.url.path.endswith('/image') else 'general'
    key=(request.client.host,bucket)
    times=request_limits[key]
    while times and times[0]<now-60: times.popleft()
    if len(times)>=(30 if bucket=='image' else 300):
        return JSONResponse({'detail':'Too many requests; please wait a minute'},status_code=429)
    times.append(now)
    if len(request_limits)>4096:
        oldest=next(iter(request_limits));request_limits.pop(oldest,None)
    allowed=urlsplit(config.BASE_URL).netloc
    if request.headers.get('host')!=allowed:
        return JSONResponse({'detail':'Unrecognized host'},status_code=400)
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.headers.get('origin')!=config.BASE_URL:
            return JSONResponse({'detail':'Request origin rejected'},status_code=403)
        try: size=int(request.headers.get('content-length','0'))
        except ValueError: size=100000
        if size>20000:
            return JSONResponse({'detail':'Request too large'},status_code=413)
        chunks=[]; received=0
        async for chunk in request.stream():
            received+=len(chunk)
            if received>20000: return JSONResponse({'detail':'Request too large'},status_code=413)
            chunks.append(chunk)
        request._body=b''.join(chunks)
    response=await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
        'Content-Security-Policy':"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        'Cache-Control':'no-store'})
    return response

class Login(BaseModel):
    password:str=Field(min_length=1,max_length=256)

@app.post('/api/login')
def login(data:Login,request:Request,response:Response):
    key=request.client.host; now=time.time(); attempts=limits[key]
    while attempts and attempts[0]<now-600: attempts.popleft()
    if len(attempts)>=8: raise HTTPException(429,'Too many attempts; wait ten minutes')
    attempts.append(now)
    try:
        salt,expected=config.OWNER_HASH.split(':')
        actual=hashlib.scrypt(data.password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        valid=hmac.compare_digest(actual,expected)
    except (ValueError,TypeError): valid=False
    if not valid: raise HTTPException(401,'Owner password is incorrect or not configured')
    token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE expires<?',(now,))
        db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),now+43200,csrf))
    response.set_cookie('trace_session',token,httponly=True,samesite='strict',secure=config.BASE_URL.startswith('https:'),max_age=43200)
    return {'owner':True,'csrf':csrf}

@app.get('/api/session')
def who(request:Request):
    user=session(request)
    return {'owner':bool(user),'csrf':user['csrf'] if user else ''}

@app.post('/api/logout')
def logout(request:Request,response:Response):
    user=owner(request)
    with connect() as db: db.execute('DELETE FROM sessions WHERE token=?',(user['token'],))
    response.delete_cookie('trace_session'); return {'ok':True}

class Filters(BaseModel):
    watch:list[str]=Field(default_factory=list,max_length=10)
    ignore:list[str]=Field(default_factory=list,max_length=10)
    threshold:float=Field(default=0,ge=0,le=1)
    timestamps:bool=False
    counters:bool=False
    ads:bool=False
    banners:bool=False
    tokens:bool=False
    @field_validator('watch','ignore')
    @classmethod
    def selectors(cls,values):
        import soupsieve
        for value in values:
            if not value.strip() or len(value)>500: raise ValueError('Selector is empty or too long')
            try: soupsieve.compile(value)
            except Exception: raise ValueError('Invalid CSS selector')
        return list(dict.fromkeys(values))

class MonitorInput(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    url:str=Field(max_length=2048)
    interval:int=Field(default=60,ge=15,le=1440)
    config:Filters=Field(default_factory=Filters)
    @field_validator('name')
    @classmethod
    def name_clean(cls,value):
        if not value.strip(): raise ValueError('Name is required')
        return value.strip()
    @field_validator('url')
    @classmethod
    def safe_url(cls,value): return validate_url(value)

class Pause(BaseModel):
    paused:bool

def visible(db,mid,request):
    row=db.execute('SELECT * FROM monitors WHERE id=?',(mid,)).fetchone()
    if not row or (not row['public'] and not session(request)): raise HTTPException(404,'Monitor not found')
    return row

def monitor_dict(row):
    result=dict(row); result['config']=json.loads(result['config']); result.pop('significant_text',None)
    return result

@app.get('/api/health')
def health():
    with connect() as db:
        row=db.execute("SELECT value FROM meta WHERE key='worker_heartbeat'").fetchone()
    alive=bool(row and time.time()-float(row[0])<180)
    return {'api':'ok','worker':'running' if alive else 'offline'}

@app.get('/api/monitors')
def monitors(request:Request):
    signed=bool(session(request))
    with connect() as db:
        rows=db.execute('SELECT * FROM monitors WHERE public=1 OR ? ORDER BY CASE status WHEN \'error\' THEN 0 WHEN \'blocked\' THEN 1 ELSE 2 END,last_changed DESC,id DESC',(signed,)).fetchall()
        return [monitor_dict(r) for r in rows]

@app.post('/api/monitors')
def create(data:MonitorInput,request:Request):
    owner(request); now=time.time()
    with connect() as db:
        if db.execute('SELECT count(*) FROM monitors').fetchone()[0]>=100: raise HTTPException(409,'This instance supports up to 100 monitors')
        mid=db.execute('INSERT INTO monitors(name,url,interval,config,next_due,created) VALUES (?,?,?,?,?,?)',
            (data.name,data.url,data.interval,data.config.model_dump_json(),now+data.interval*60,now)).lastrowid
        enqueue(db,db.execute('SELECT * FROM monitors WHERE id=?',(mid,)).fetchone(),now)
    return {'id':mid}

@app.get('/api/monitors/{mid}')
def detail(mid:int,request:Request):
    with connect() as db:
        row=visible(db,mid,request)
        result=monitor_dict(row)
        result['versions']=[dict(v) for v in db.execute('SELECT id,revision,captured,meaningful,reason FROM versions WHERE monitor_id=? ORDER BY id DESC',(mid,))]
        result['checks']=[dict(v) for v in db.execute('SELECT * FROM checks WHERE monitor_id=? ORDER BY id DESC LIMIT 30',(mid,))]
        recent=[r for r in result['checks'][:5]]
        result['unstable']=len(recent)==5 and all(r['reason']=='Meaningful change' for r in recent)
        result['checking']=bool(db.execute('SELECT id FROM jobs WHERE monitor_id=?',(mid,)).fetchone())
        return result

@app.put('/api/monitors/{mid}')
def update(mid:int,data:MonitorInput,request:Request):
    owner(request)
    with connect() as db:
        row=visible(db,mid,request)
        if row['public']: raise HTTPException(409,'Demo monitors are managed by the fixture generator')
        changed=row['url']!=data.url or json.loads(row['config'])!=data.config.model_dump()
        db.execute('UPDATE monitors SET name=?,url=?,interval=?,config=?,revision=revision+?,significant_text=CASE WHEN ? THEN NULL ELSE significant_text END,next_due=? WHERE id=?',
                   (data.name,data.url,data.interval,data.config.model_dump_json(),int(changed),changed,time.time(),mid))
        db.execute('DELETE FROM jobs WHERE monitor_id=?',(mid,))
    return {'ok':True,'new_baseline':changed}

@app.post('/api/monitors/{mid}/pause')
def pause(mid:int,data:Pause,request:Request):
    owner(request)
    with connect() as db:
        row=visible(db,mid,request)
        if row['public']: raise HTTPException(409,'Demo monitor is managed by fixture generator')
        db.execute('UPDATE monitors SET paused=?,next_due=? WHERE id=?',(data.paused,time.time(),mid))
        db.execute('DELETE FROM jobs WHERE monitor_id=?',(mid,))
    return {'ok':True}

@app.post('/api/monitors/{mid}/check')
def manual(mid:int,request:Request):
    owner(request)
    with connect() as db:
        row=visible(db,mid,request)
        if row['public'] or row['paused']: raise HTTPException(409,'Resume an owner monitor before checking')
        if row['last_checked'] and time.time()-row['last_checked']<30: raise HTTPException(429,'Please wait 30 seconds between checks')
        enqueue(db,row,time.time())
    return {'ok':True}

@app.delete('/api/monitors/{mid}')
def delete(mid:int,request:Request):
    owner(request)
    with connect() as db:
        row=visible(db,mid,request)
        if row['public']: raise HTTPException(409,'Demo monitor is managed by fixture generator')
        db.execute('DELETE FROM monitors WHERE id=?',(mid,))
    return {'ok':True}

def version(db,vid,request):
    row=db.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone()
    if not row: raise HTTPException(404,'Version not found or removed by retention')
    visible(db,row['monitor_id'],request)
    return row

@app.get('/api/versions/{vid}')
def version_detail(vid:int,request:Request):
    with connect() as db:
        row=version(db,vid,request)
        return {'id':vid,'text':row['text'],'geometry':json.loads(row['geometry']),'captured':row['captured'],'revision':row['revision']}

@app.get('/api/versions/{vid}/image')
def screenshot(vid:int,request:Request):
    with connect() as db: row=version(db,vid,request)
    return Response(row['image'],media_type='image/png')

@app.post('/api/versions/{vid}/preview')
def preview(vid:int,data:Filters,request:Request):
    owner(request)
    with connect() as db: row=version(db,vid,request)
    try:
        text,masks=extract(row['html'],json.loads(row['geometry']),data.model_dump())
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(row['html'],'html.parser')
        counts={s:len(soup.select(s)) for s in data.watch+data.ignore}
        return {'text':text,'masks':masks,'counts':counts}
    except ValueError as exc: raise HTTPException(422,str(exc))

@app.get('/api/compare/{a}/{b}')
def comparison(a:int,b:int,request:Request):
    with connect() as db:
        before,after=version(db,a,request),version(db,b,request)
    if before['monitor_id']!=after['monitor_id']: raise HTTPException(400,'Choose two versions of the same monitor')
    old,new=before['text'].splitlines(),after['text'].splitlines()
    lines=[]
    for tag,i,j,k,l in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes():
        if tag=='equal': lines.extend({'kind':'same','text':s} for s in old[i:j])
        else:
            lines.extend({'kind':'removed','text':s} for s in old[i:j])
            lines.extend({'kind':'added','text':s} for s in new[k:l])
    return {'lines':lines,'different_config':before['revision']!=after['revision']}

@app.get('/api/compare/{a}/{b}/image')
def visual_comparison(a:int,b:int,request:Request):
    with connect() as db: before,after=version(db,a,request),version(db,b,request)
    if before['monitor_id']!=after['monitor_id']: raise HTTPException(400,'Choose versions of the same monitor')
    return Response(image_diff(before['image'],after['image'],json.loads(before['masks'])+json.loads(after['masks'])),media_type='image/png')

@app.get('/api/notifications')
def notifications(request:Request):
    owner(request)
    with connect() as db:
        values=dict(db.execute('SELECT key,value FROM settings').fetchall())
        rows=[dict(r) for r in db.execute('SELECT id,channel,state,attempts,error,due FROM outbox ORDER BY id DESC LIMIT 30')]
    return {'channels':{c:{'configured':configured(c),'enabled':values.get(c)=='on'} for c in ('email','discord')},'deliveries':rows}

class Channels(BaseModel):
    email:bool=False
    discord:bool=False

@app.put('/api/notifications')
def notification_settings(data:Channels,request:Request):
    owner(request)
    with connect() as db:
        for channel,enabled in data.model_dump().items():
            if enabled and not configured(channel): raise HTTPException(422,f'Configure {channel} credentials on the server first')
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(channel,'on' if enabled else 'off'))
    return {'ok':True}


@app.post('/api/notifications/{oid}/retry')
def retry_notification(oid:int,request:Request):
    owner(request)
    with connect() as db:
        row=db.execute('SELECT * FROM outbox WHERE id=?',(oid,)).fetchone()
        if not row or row['state'] not in ('failed','uncertain'): raise HTTPException(409,'Only failed or uncertain deliveries can be retried')
        db.execute("UPDATE outbox SET state='pending',attempts=0,error=NULL,due=? WHERE id=?",(time.time(),oid))
    return {'ok':True}

DIST=config.ROOT/'frontend'/'dist'
if DIST.exists():
    app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')

@app.get('/')
def index():
    if not (DIST/'index.html').exists(): raise HTTPException(503,'Build the frontend first')
    return FileResponse(DIST/'index.html')
