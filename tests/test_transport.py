"""Exercise production Renderer + proxy against a controlled HTTP server.

Only this test replaces the proxy's socket connector to map one approved test IP
onto the fixture server. No application setting can enable this adapter.
"""
import asyncio
import pytest
from traceapp import capture,proxy
from traceapp.capture import Renderer,CaptureError
from traceapp.policy import PolicyError

async def test_browser_http_failures_robots_and_redirect_boundary(monkeypatch):
    requests=[];connections=[]
    async def fixture(reader,writer):
        request=await reader.readuntil(b'\r\n\r\n')
        path=request.split(b' ')[1].decode();requests.append(path)
        status='200 OK';headers='';body='<html><head><meta charset="UTF-8"></head><body><main id="content">Actual fixture response</main></body></html>'
        if path=='/robots.txt':body='User-agent: *\nDisallow: /forbidden\n'
        elif path=='/fail':status='500 Internal Server Error';body='temporary failure'
        elif path=='/challenge':body='<html><body>Verify you are human</body></html>'
        elif path=='/redirect':status='302 Found';headers='Location: http://127.0.0.1/private\r\n';body=''
        raw=body.encode()
        writer.write((f'HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(raw)}\r\nConnection: close\r\n'+headers+'\r\n').encode()+raw)
        await writer.drain();writer.close()
    fixture_server=await asyncio.start_server(fixture,'127.0.0.1',0)
    fixture_port=fixture_server.sockets[0].getsockname()[1]
    original=asyncio.open_connection
    async def approved(host,port):
        if host!='controlled.example.test':raise PolicyError('Not a fixture host')
        return ['93.184.216.34']
    async def test_connect(ip,port):
        assert ip=='93.184.216.34' and port==80
        connections.append((ip,port))
        return await original('127.0.0.1',fixture_port)
    monkeypatch.setattr(proxy,'resolve_public',approved)
    monkeypatch.setattr(proxy.asyncio,'open_connection',test_connect)
    proxy_server=await asyncio.start_server(proxy.handle,'127.0.0.1',0)
    monkeypatch.setattr(capture,'PROXY',f'http://127.0.0.1:{proxy_server.sockets[0].getsockname()[1]}')
    renderer=Renderer()
    try:
        result=await renderer.capture('http://controlled.example.test/page')
        assert result.image.startswith(b'\x89PNG') and 'Actual fixture response' in result.html
        with pytest.raises(CaptureError,match='HTTP 500'):
            await renderer.capture('http://controlled.example.test/fail')
        with pytest.raises(CaptureError,match='Access challenge'):
            await renderer.capture('http://controlled.example.test/challenge')
        with pytest.raises(CaptureError,match='robots.txt'):
            await renderer.capture('http://controlled.example.test/forbidden')
        with pytest.raises(Exception):
            await renderer.capture('http://controlled.example.test/redirect')
        assert '/private' not in requests and '/forbidden' not in requests
        assert requests.count('/robots.txt')==1
        assert connections
    finally:
        proxy_server.close();fixture_server.close()
        await proxy_server.wait_closed();await fixture_server.wait_closed()
