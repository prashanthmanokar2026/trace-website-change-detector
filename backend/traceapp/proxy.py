"""Bounded HTTP CONNECT proxy; resolve once and connect to that literal IP.

Run on a private interface. Deployment isolates the browser on an internal
network with only this proxy as an outbound path. Never expose the proxy publicly.
"""
import asyncio
import os
import time
from collections import deque
from urllib.parse import urlsplit
from .policy import resolve_public, validate_url

LIMIT = 12 * 1024 * 1024
slots = asyncio.Semaphore(16)
transfers = deque()
host_last = {}

def charge(size):
    now=time.monotonic()
    while transfers and transfers[0][0]<now-60: transfers.popleft()
    if sum(n for _,n in transfers)+size>32*1024*1024: raise ValueError("global transfer budget")
    transfers.append((now,size))

async def handle(reader, writer):
    remote = None
    try:
        async with slots, asyncio.timeout(55):
            header = await reader.readuntil(b'\r\n\r\n')
            if len(header) > 16384:
                raise ValueError('headers')
            method, target, _ = header.split(b'\r\n', 1)[0].decode('ascii').split(' ')
            if method == 'CONNECT':
                u = urlsplit('https://' + target)
                validate_url('https://' + target)
                if u.port != 443:
                    raise ValueError('port')
                host, port = u.hostname, 443
            elif method in ('GET', 'HEAD'):
                u = urlsplit(validate_url(target))
                if u.scheme != 'http':
                    raise ValueError('scheme')
                host, port = u.hostname, 80
            else:
                raise ValueError('method')
            delay=max(0,host_last.get(host,0)-time.monotonic())
            host_last[host]=time.monotonic()+delay+0.25
            if len(host_last)>1000:
                for key in list(host_last):
                    if host_last[key]<time.monotonic()-60: host_last.pop(key,None)
            await asyncio.sleep(delay)
            addresses = await resolve_public(host, port)
            upstream, remote = await asyncio.open_connection(addresses[0], port)
            if method == 'CONNECT':
                writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            else:
                path = u.path + ('?' + u.query if u.query else '')
                lines = header.split(b'\r\n')[1:]
                safe = [x for x in lines if x and x.split(b':',1)[0].lower() not in
                        (b'host', b'connection', b'proxy-connection', b'proxy-authorization', b'content-length', b'transfer-encoding')]
                remote.write((method + ' ' + path + ' HTTP/1.1\r\nHost: ' + host + '\r\nConnection: close\r\n').encode() + b'\r\n'.join(safe) + b'\r\n\r\n')
                await remote.drain()
            await writer.drain()
            budget = [0]
            async def pipe(src, dst):
                while data := await src.read(32768):
                    charge(len(data))
                    budget[0] += len(data)
                    if budget[0] > LIMIT:
                        raise ValueError('transfer limit')
                    dst.write(data)
                    await dst.drain()
            tasks = [asyncio.create_task(pipe(reader, remote)), asyncio.create_task(pipe(upstream, writer))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:
                    if task.done():
                        task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        try:
            writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain()
        except Exception:
            pass
    finally:
        if remote:
            remote.close()
        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle, os.getenv('TRACE_PROXY_BIND','127.0.0.1'), 8899, limit=16385)
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.run(main())
