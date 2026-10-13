"""Run inside the deployed worker before accepting arbitrary monitoring URLs."""
import asyncio
from traceapp.capture import Renderer
from traceapp.policy import PolicyError
import httpx

async def main():
    for host,port in [('1.1.1.1',443),('169.254.169.254',80)]:
        try:
            connection=await asyncio.wait_for(asyncio.open_connection(host,port),2)
        except (OSError,TimeoutError): pass
        else:
            connection[1].close(); raise SystemExit('FAIL: worker has direct outbound connectivity')
    from traceapp.config import PROXY
    async with httpx.AsyncClient(proxy=PROXY,timeout=10,trust_env=False) as client:
        for url in ['http://127.0.0.1/','http://169.254.169.254/','http://10.0.0.1/']:
            try: response=await client.get(url)
            except httpx.HTTPError: continue
            assert response.status_code==403, 'Proxy accepted a private destination'
    capture=await Renderer().capture('https://example.com/')
    assert len(capture.image)>1000
    print('PASS: direct egress denied, private proxy targets denied, sandboxed public capture works')
asyncio.run(main())
