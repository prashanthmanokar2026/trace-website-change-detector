import asyncio
import json
import socket
import time
from io import BytesIO
import pytest
from PIL import Image
from traceapp import db
from traceapp.policy import validate_url,resolve_public,PolicyError
from traceapp.queue import schedule,claim,complete
from traceapp.capture import CaptureError
from traceapp.content import extract,image_diff
from traceapp.worker import tick
from traceapp.notify import deliver_one
from tests.fixtures import FixtureRenderer


def add_monitor(url='https://fixture.trace.test/scholarship',config=None):
    now=time.time()
    with db.connect() as conn:
        return conn.execute('INSERT INTO monitors(name,url,interval,config,next_due,created) VALUES (?,?,?,?,?,?)',
          ('Fixture',url,15,json.dumps(config or {}),now,now)).lastrowid

def clear_domain():
    with db.connect() as c: c.execute('DELETE FROM domains')

def due(mid):
    clear_domain()
    with db.connect() as c: c.execute('UPDATE monitors SET next_due=0 WHERE id=?',(mid,))

@pytest.mark.parametrize('url',['http://127.0.0.1','http://10.0.0.1','http://169.254.169.254','http://[::1]','http://[::ffff:127.0.0.1]',
  'file:///etc/passwd','https://name:secret@example.com','https://example.com:8443','http://localhost','http://foo.local','http://2130706433','http://example.com\\@127.0.0.1'])
def test_unsafe_urls(url):
    with pytest.raises(ValueError): validate_url(url)

def test_url_semantics():
    assert validate_url('https://EXAMPLE.com/x?b=2&a=1#section')=='https://example.com/x?b=2&a=1'

async def test_mixed_dns_rejected(monkeypatch):
    loop=asyncio.get_running_loop()
    async def answers(*a,**kw): return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
    monkeypatch.setattr(loop,'getaddrinfo',answers)
    with pytest.raises(PolicyError): await resolve_public('example.com',443)

async def test_proxy_connects_validated_ip(monkeypatch):
    from traceapp import proxy
    connected=[]
    async def resolve(host,port): return ['93.184.216.34']
    async def connect(ip,port):
        connected.append((ip,port)); raise ConnectionRefusedError()
    monkeypatch.setattr(proxy,'resolve_public',resolve);monkeypatch.setattr(proxy.asyncio,'open_connection',connect)
    reader=asyncio.StreamReader();reader.feed_data(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n');reader.feed_eof()
    class Writer:
        def write(self,data): pass
        async def drain(self): pass
        def close(self): pass
        async def wait_closed(self): pass
    await proxy.handle(reader,Writer())
    assert connected==[('93.184.216.34',443)]

async def test_real_capture_filters_history_failure_and_reversion(database):
    conf={'timestamps':True,'ads':True,'counters':True,'tokens':True}
    mid=add_monitor(config=conf);renderer=FixtureRenderer()
    await tick(renderer)
    with db.connect() as c:
        first=c.execute('SELECT * FROM versions').fetchone()
        assert Image.open(BytesIO(first['image'])).size==(1280,900)
        assert first['meaningful']==0
    renderer.noise=30;due(mid);await tick(renderer)
    with db.connect() as c: assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==1
    renderer.stage=1;due(mid);await tick(renderer)
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==2
        assert c.execute('SELECT last_changed FROM monitors').fetchone()[0]
        last=c.execute('SELECT * FROM versions ORDER BY id DESC').fetchone()
        image=Image.open(BytesIO(image_diff(first['image'],last['image'],json.loads(first['masks'])+json.loads(last['masks']))))
        assert image.size==(1280,900)
    renderer.failure=CaptureError('CAPTCHA',blocked=True);due(mid);await tick(renderer)
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==2
        assert c.execute('SELECT status FROM monitors').fetchone()[0]=='blocked'
    renderer.failure=None;renderer.stage=0;due(mid);await tick(renderer)
    with db.connect() as c: assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==3

async def test_200_subscriptions_share_one_real_render(database):
    for _ in range(200): add_monitor()
    renderer=FixtureRenderer();await tick(renderer)
    assert renderer.calls==1 and renderer.requests==1
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==200
        assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==0

async def test_missing_selector_keeps_baseline(database):
    mid=add_monitor();r=FixtureRenderer();await tick(r)
    with db.connect() as c: c.execute('UPDATE monitors SET config=? WHERE id=?',(json.dumps({'watch':['#missing']}),mid))
    due(mid);await tick(r)
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM versions').fetchone()[0]==1
        assert c.execute('SELECT status FROM monitors').fetchone()[0]=='error'

async def test_geometry_selectors_and_number_preservation(database):
    capture=await FixtureRenderer().capture('https://fixture.trace.test')
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(capture.html,'html.parser')
    for el in capture.geometry:
        if soup.select(el['selector']): assert len(soup.select(el['selector']))==1
    text,_=extract(capture.html,capture.geometry,{'watch':['#announcement'],'ignore':['#description']})
    assert '25,000' in text and '30 October' in text
    assert 'Applications open' not in text


def test_claim_restart_and_pause_race(database):
    mid=add_monitor();schedule();jobs=claim();assert len(jobs)==1;assert claim()==[]
    token=jobs[0]['token']
    with db.connect() as c: c.execute('UPDATE jobs SET lease=0')
    clear_domain();schedule();recovered=claim();assert recovered[0]['token']!=token
    with db.connect() as c: c.execute('UPDATE monitors SET paused=1 WHERE id=?',(mid,))
    complete(recovered[0],error=CaptureError('failure'))
    with db.connect() as c: assert c.execute('SELECT count(*) FROM checks').fetchone()[0]==0


def test_retries_bounded_and_schedules_coalesced(database):
    mid=add_monitor();schedule();jobs=claim();complete(jobs[0],error=CaptureError('timeout'))
    with db.connect() as c:
        job=c.execute('SELECT * FROM jobs').fetchone();assert job['state']=='pending' and job['attempts']==1
        assert c.execute('SELECT next_due FROM monitors').fetchone()[0]>time.time()
        c.execute('UPDATE jobs SET due=0,attempts=2')
    clear_domain();jobs=claim();complete(jobs[0],error=CaptureError('timeout'))
    with db.connect() as c: assert c.execute('SELECT count(*) FROM jobs').fetchone()[0]==0


def test_api_access_csrf_validation_and_deletion(signed):
    payload={'name':'Example','url':'https://example.com','interval':15}
    assert signed.post('/api/monitors',json={**payload,'interval':5}).status_code==422
    assert signed.post('/api/monitors',json={**payload,'url':'http://127.0.0.1'}).status_code==422
    mid=signed.post('/api/monitors',json=payload).json()['id']
    assert signed.post(f'/api/monitors/{mid}/pause',json={'paused':True},headers={'x-csrf-token':'bad'}).status_code==403
    assert signed.get('/api/monitors',headers={'Host':'evil.test'}).status_code==400
    assert signed.delete(f'/api/monitors/{mid}').status_code==200
    assert signed.get(f'/api/monitors/{mid}').status_code==404

async def test_public_cannot_read_owner_artifacts(client,database):
    mid=add_monitor();await tick(FixtureRenderer())
    assert client.get('/api/monitors').json()==[]
    assert client.get(f'/api/monitors/{mid}').status_code==404
    assert client.get('/api/versions/1/image').status_code==404
    assert client.get('/api/compare/1/1').status_code==404
    assert client.post('/api/monitors',json={'name':'x','url':'https://example.com'}).status_code==401

async def test_outbox_unique_retry_and_uncertain(database):
    mid=add_monitor();r=FixtureRenderer()
    with db.connect() as c: c.execute("INSERT INTO settings VALUES ('email','on')")
    await tick(r);r.stage=1;due(mid);await tick(r);due(mid);await tick(r)
    with db.connect() as c: assert c.execute('SELECT count(*) FROM outbox').fetchone()[0]==1
    calls=[]
    async def failure(channel,body): calls.append(body);raise ValueError('provider refusal')
    await deliver_one(failure)
    with db.connect() as c:
        assert c.execute('SELECT state FROM outbox').fetchone()[0]=='pending';c.execute('UPDATE outbox SET due=0')
    async def uncertain(channel,body): raise TimeoutError()
    await deliver_one(uncertain)
    with db.connect() as c: assert c.execute('SELECT state FROM outbox').fetchone()[0]=='uncertain'
    assert not await deliver_one(failure)

async def test_config_revision_and_delete_cascade(signed):
    data={'name':'Example','url':'https://fixture.trace.test/page','interval':15}
    mid=signed.post('/api/monitors',json=data).json()['id']
    renderer=FixtureRenderer();await tick(renderer)
    response=signed.put(f'/api/monitors/{mid}',json={**data,'config':{'watch':['#announcement']}})
    assert response.json()['new_baseline']
    due(mid);await tick(renderer)
    with db.connect() as c:
        rows=c.execute('SELECT revision,meaningful FROM versions ORDER BY id').fetchall()
        assert [r['revision'] for r in rows]==[1,2]
        assert all(not r['meaningful'] for r in rows)
    assert signed.delete(f'/api/monitors/{mid}').status_code==200
    with db.connect() as c:
        for table in ['versions','checks','jobs','outbox']:
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0

def test_smtp_adapter_uses_tls_and_expected_recipient(monkeypatch):
    from traceapp import notify
    sent=[]
    class SMTP:
        def __init__(self,*args,**kwargs): pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def starttls(self,context):sent.append('tls')
        def login(self,user,password):sent.append('auth')
        def send_message(self,message):sent.append(message)
    for key,value in {'TRACE_SMTP_HOST':'smtp.example.test','TRACE_EMAIL_FROM':'trace@example.test','TRACE_EMAIL_TO':'owner@example.test','TRACE_SMTP_USER':'fixture','TRACE_SMTP_PASSWORD':'test-value'}.items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr(notify.smtplib,'SMTP',SMTP)
    notify.email_send('Actual test summary')
    assert sent[:2]==['tls','auth']
    assert sent[2]['To']=='owner@example.test'
    assert 'Actual test summary' in sent[2].get_content()

async def test_discord_adapter_restricts_destinations(monkeypatch):
    from traceapp.notify import send
    monkeypatch.setenv('TRACE_DISCORD_WEBHOOK','http://127.0.0.1/steal')
    with pytest.raises(ValueError,match='Unsupported'):
        await send('discord','test')

async def test_disabled_outbox_does_not_block_enabled_channel(database):
    add_monitor()
    with db.connect() as c:
        c.execute("INSERT INTO settings VALUES ('discord','on')")
        c.execute("INSERT INTO outbox(monitor_id,version_id,channel,body,due) VALUES (1,1,'email','x',0)")
        c.execute("INSERT INTO outbox(monitor_id,version_id,channel,body,due) VALUES (1,1,'discord','x',0)")
    sent=[]
    async def sender(channel,body): sent.append(channel)
    assert await deliver_one(sender)
    assert sent==['discord']

def test_schema_upgrade_is_idempotent(database):
    db.init();db.init()
    with db.connect() as c:
        assert c.execute('SELECT version FROM schema_version').fetchone()[0]==2
        columns=[r['name'] for r in c.execute('PRAGMA table_info(outbox)')]
        assert columns.count('before_id')==1

async def test_pending_notification_retains_both_comparison_versions(database,monkeypatch):
    import traceapp.queue as queue
    monkeypatch.setattr(queue,'RETENTION',1)
    mid=add_monitor();renderer=FixtureRenderer();await tick(renderer)
    with db.connect() as c:c.execute("INSERT INTO settings VALUES ('email','on')")
    renderer.stage=1;due(mid);await tick(renderer)
    with db.connect() as c:
        alert=c.execute('SELECT * FROM outbox').fetchone()
        assert c.execute('SELECT id FROM versions WHERE id=?',(alert['before_id'],)).fetchone()
        assert c.execute('SELECT id FROM versions WHERE id=?',(alert['version_id'],)).fetchone()

def test_concurrent_first_start_migration(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(db,'DATA',tmp_path/'new-instance')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:db.init(),range(8)))
    with db.connect() as c:assert c.execute('SELECT version FROM schema_version').fetchone()[0]==2
